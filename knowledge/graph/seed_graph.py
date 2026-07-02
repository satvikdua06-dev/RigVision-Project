"""Seed the Neo4j knowledge graph from the project's two sources of truth:

  cad/zone_definitions.json                    -> Zones, Devices, Sensors (physical topology)
  knowledge/thresholds/threshold_registry.json -> Manuals, ThresholdSpecs (manual-derived limits)

plus the failure-mode/symptom/action ontology mirroring
knowledge/documents/ONGC_Device_Manuals.txt (device sections + the HSE area standard).

Conventions (keep these constant across the whole project):
  - Sensor/symptom types are the live pipeline types:
      temperature | vibration | noise | gas_h2s | pressure
  - Floor-1 rig zones (zone_*_f1) reuse their base room's topology, so *_f1
    equipment is MERGED into the base device (pump_01_f1 -> pump_01); its
    sensors attach to that base device.
  - Action nodes are {id, name}; the relationship is REQUIRES_ACTION.
  - Failure modes exist at two levels:
      (:Device)-[:CAN_EXPERIENCE]->(:FailureMode)   equipment failures (device manuals)
      (:Zone)-[:CAN_EXPERIENCE]->(:FailureMode)     area/HSE hazards (safety standard)

Graph model:
  (:Zone)-[:CONTAINS]->(:Device)
  (:Device)-[:HAS_SENSOR]->(:Sensor)
  (:Device)-[:HAS_MANUAL]->(:Manual)
  (:Manual)-[:DEFINES_THRESHOLD]->(:ThresholdSpec)
  (:Device)-[:HAS_THRESHOLD]->(:ThresholdSpec)
  (:Zone)-[:HAS_ENV_THRESHOLD]->(:ThresholdSpec)
  (:Device|:Zone)-[:CAN_EXPERIENCE]->(:FailureMode)
  (:FailureMode)-[:INDICATED_BY]->(:Symptom)
  (:FailureMode)-[:REQUIRES_ACTION]->(:Action)
"""

import json
import logging
import os

from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ZONE_DEFS_PATH = os.path.join(REPO_ROOT, "cad", "zone_definitions.json")
REGISTRY_PATH = os.path.join(REPO_ROOT, "knowledge", "thresholds", "threshold_registry.json")

# Rig zone ids -> KG Zone ids. Floor-1 variants reuse their base room's topology.
ZONE_TO_KG = {
    "zone_a": "room_1", "zone_b": "room_2", "corridor": "corridor",
    "zone_a_f1": "room_1", "zone_b_f1": "room_2", "corridor_f1": "corridor",
}
KG_ZONES = [
    {"id": "room_1", "name": "Room A", "location_type": "work_area"},
    {"id": "room_2", "name": "Room B", "location_type": "work_area"},
    {"id": "corridor", "name": "Corridor", "location_type": "passage"},
]

# Equipment type -> manufacturer model (the manual that governs it).
# Types without an entry (storage, safety) have no manual-derived thresholds.
TYPE_TO_MODEL = {
    "pump": {"model": "RV-MP-1600", "manufacturer": "RigVision Systems", "equipment_class": "rotating"},
    "control_panel": {"model": "VoltGuard CP-440", "manufacturer": "VoltGuard", "equipment_class": "static"},
    "compressor": {"model": "ACME-COMP-2200", "manufacturer": "ACME", "equipment_class": "rotating"},
    "wellhead": {"model": "WH-5000 Series", "manufacturer": "WH Industries", "equipment_class": "static"},
}

SYMPTOM_CONDITIONS = {
    "temperature": "High Temperature",
    "vibration": "High Vibration",
    "noise": "High Noise",
    "gas_h2s": "H2S Gas Detected",
    "pressure": "High Pressure",
}

# Device failure modes per model (mirrors the device manual sections).
# Action names must match the quoted 'Required Action' strings in the manuals.
DEVICE_FAILURE_MODES = {
    "RV-MP-1600": [
        {"id": "fm_mp1600_bearing_seizure", "name": "Main Bearing Seizure",
         "symptoms": ["temperature", "vibration"], "action": "Replace Main Bearing Assembly"},
        {"id": "fm_mp1600_liner_wash", "name": "Liner Wash (Piston/Liner Wear)",
         "symptoms": ["vibration"], "action": "Replace Liner and Piston"},
        {"id": "fm_mp1600_packing_gland", "name": "Packing Gland Failure",
         "symptoms": ["noise", "vibration"], "action": "Repack Stuffing Box"},
    ],
    "VoltGuard CP-440": [
        {"id": "fm_cp440_line_blockage", "name": "Hydraulic Line Blockage",
         "symptoms": ["pressure"], "action": "Flush Hydraulic Control Line"},
        {"id": "fm_cp440_relief_valve", "name": "Relief Valve Failure",
         "symptoms": ["pressure"], "action": "Replace Relief Valve"},
        {"id": "fm_cp440_overheating", "name": "Panel Overheating (Ventilation Blockage)",
         "symptoms": ["temperature"], "action": "Clear Panel Ventilation and Replace Filter"},
    ],
    "ACME-COMP-2200": [
        {"id": "fm_comp2200_motor_burnout", "name": "Motor Burnout",
         "symptoms": ["temperature", "vibration"], "action": "Replace Motor"},
        {"id": "fm_comp2200_discharge_valve", "name": "Discharge Valve Failure",
         "symptoms": ["pressure", "temperature"], "action": "Replace Valve Plate Assembly"},
        {"id": "fm_comp2200_bearing_wear", "name": "Bearing Wear",
         "symptoms": ["vibration"], "action": "Replace Bearings"},
    ],
    "WH-5000 Series": [
        {"id": "fm_wh5000_annular_seal", "name": "Annular Seal Leak",
         "symptoms": ["gas_h2s"], "action": "Activate Emergency Shutdown and Replace Annular Seal"},
        {"id": "fm_wh5000_choke_erosion", "name": "Choke Erosion",
         "symptoms": ["noise"], "action": "Replace Choke Bean"},
        {"id": "fm_wh5000_master_valve", "name": "Master Valve Passing",
         "symptoms": ["noise", "gas_h2s"], "action": "Lap or Replace Master Valve Gate"},
    ],
}

# Area/HSE hazards (HSE-2025-04 Section 3) — apply to EVERY zone, so an alert in
# a zone with no instrumented equipment (e.g. the corridor) still resolves to a
# known failure mode with a protocol.
ZONE_FAILURE_MODES = [
    {"id": "fm_area_h2s_accumulation", "name": "Area H2S Gas Accumulation",
     "symptoms": ["gas_h2s"], "action": "Evacuate Zone and Ventilate"},
    {"id": "fm_area_heat_stress", "name": "Heat Stress Hazard",
     "symptoms": ["temperature"], "action": "Remove Heat Source and Ventilate"},
    {"id": "fm_area_noise", "name": "Excessive Area Noise",
     "symptoms": ["noise"], "action": "Enforce Hearing Protection and Locate Noise Source"},
    {"id": "fm_area_vibration", "name": "Structural Vibration Hazard",
     "symptoms": ["vibration"], "action": "Stop Equipment and Inspect Structure"},
    {"id": "fm_area_overpressure", "name": "Service Line Overpressure",
     "symptoms": ["pressure"], "action": "Isolate and Depressurize Service Line"},
]

CONSTRAINTS = [
    "CREATE CONSTRAINT zone_id IF NOT EXISTS FOR (z:Zone) REQUIRE z.id IS UNIQUE",
    "CREATE CONSTRAINT device_id IF NOT EXISTS FOR (d:Device) REQUIRE d.id IS UNIQUE",
    "CREATE CONSTRAINT sensor_id IF NOT EXISTS FOR (s:Sensor) REQUIRE s.id IS UNIQUE",
    "CREATE CONSTRAINT manual_id IF NOT EXISTS FOR (m:Manual) REQUIRE m.id IS UNIQUE",
    "CREATE CONSTRAINT threshold_id IF NOT EXISTS FOR (t:ThresholdSpec) REQUIRE t.id IS UNIQUE",
    "CREATE CONSTRAINT failure_mode_id IF NOT EXISTS FOR (f:FailureMode) REQUIRE f.id IS UNIQUE",
    "CREATE CONSTRAINT action_id IF NOT EXISTS FOR (a:Action) REQUIRE a.id IS UNIQUE",
    "CREATE CONSTRAINT symptom_type IF NOT EXISTS FOR (s:Symptom) REQUIRE s.type IS UNIQUE",
]


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _base_device_id(equipment_id: str) -> str:
    """pump_01_f1 -> pump_01 (floor-1 equipment merges into its base device)."""
    return equipment_id[:-3] if equipment_id.endswith("_f1") else equipment_id


def build_payload():
    """Flatten zone_definitions + threshold_registry into UNWIND-able row lists."""
    zone_defs = _load(ZONE_DEFS_PATH)["zones"]
    registry = _load(REGISTRY_PATH)

    devices_by_id: dict = {}
    sensors, has_sensor = [], []
    for rig_zone_id, zdef in zone_defs.items():
        kg_zone = ZONE_TO_KG.get(rig_zone_id, rig_zone_id)
        device_owned = set()
        for eq in zdef.get("equipment", []):
            did = _base_device_id(eq["id"])
            if did not in devices_by_id:
                meta = TYPE_TO_MODEL.get(eq["type"], {})
                devices_by_id[did] = {
                    "id": did, "name": eq["name"].replace(" (F1)", ""), "type": eq["type"],
                    "model": meta.get("model"), "manufacturer": meta.get("manufacturer"),
                    "equipment_class": meta.get("equipment_class"),
                    "kg_zone_id": kg_zone,
                }
            for sid in eq.get("sensors", []):
                has_sensor.append({"device_id": did, "sensor_id": sid})
                device_owned.add(sid)
        
        # Ensure we have a virtual environmental monitor device for this kg_zone
        env_dev_id = f"env_monitor_{kg_zone}"
        if env_dev_id not in devices_by_id:
            zone_names = {
                "room_1": "Room A",
                "room_2": "Room B",
                "corridor": "Corridor"
            }
            z_display_name = zone_names.get(kg_zone, kg_zone.replace("_", " ").title())
            devices_by_id[env_dev_id] = {
                "id": env_dev_id,
                "name": f"{z_display_name} Environmental Monitor",
                "type": "environmental_monitor",
                "model": "EnvMonitor-V1",
                "manufacturer": "RigVision Systems",
                "equipment_class": "static",
                "kg_zone_id": kg_zone,
            }

        for s in zdef.get("sensors", []):
            is_device_owned = s["id"] in device_owned
            sensors.append({
                "id": s["id"], "type": s["type"], "unit": s.get("unit", ""),
                "rig_zone_id": rig_zone_id, "kg_zone_id": kg_zone,
                "scope": "device" if is_device_owned else "zone",
            })
            if not is_device_owned:
                has_sensor.append({"device_id": env_dev_id, "sensor_id": s["id"]})
    devices = list(devices_by_id.values())

    manuals = registry["manuals"]
    specs = []
    for sp in registry["specs"]:
        specs.append({
            "id": sp["threshold_id"], "scope": sp["scope"],
            "device_model": sp.get("device_model"),
            "sensor_type": sp["sensor_type"], "metric": sp["metric"], "unit": sp["unit"],
            "normal_min": sp["normal_range"]["min"], "normal_max": sp["normal_range"]["max"],
            "warning_min": sp["warning_min"], "critical_min": sp["critical_min"],
            "operating_mode": sp.get("operating_mode"),
            "manual_id": sp["source"]["manual_id"],
            "source_section": sp["source"].get("section"),
            "source_text": sp["source"].get("text"),
            "confidence": sp.get("confidence"),
            "validated_by_human": sp.get("validated_by_human", False),
        })

    device_fms = [{**fm, "model": model}
                  for model, fms in DEVICE_FAILURE_MODES.items() for fm in fms]
    symptoms = [{"type": t, "condition": c} for t, c in SYMPTOM_CONDITIONS.items()]
    return devices, sensors, has_sensor, manuals, specs, device_fms, symptoms


def create_topology(tx, payload):
    devices, sensors, has_sensor, manuals, specs, device_fms, symptoms = payload

    tx.run("MATCH (n) DETACH DELETE n")

    tx.run("UNWIND $rows AS r CREATE (:Zone {id: r.id, name: r.name, location_type: r.location_type})",
           rows=KG_ZONES)

    tx.run("""
        UNWIND $rows AS r
        MATCH (z:Zone {id: r.kg_zone_id})
        CREATE (d:Device {id: r.id, name: r.name, type: r.type, model: r.model,
                          manufacturer: r.manufacturer, equipment_class: r.equipment_class})
        CREATE (z)-[:CONTAINS]->(d)
    """, rows=devices)

    tx.run("""
        UNWIND $rows AS r
        CREATE (:Sensor {id: r.id, type: r.type, unit: r.unit, scope: r.scope,
                         rig_zone_id: r.rig_zone_id, kg_zone_id: r.kg_zone_id})
    """, rows=sensors)

    tx.run("""
        UNWIND $rows AS r
        MATCH (d:Device {id: r.device_id})
        MATCH (s:Sensor {id: r.sensor_id})
        CREATE (d)-[:HAS_SENSOR]->(s)
    """, rows=has_sensor)

    tx.run("""
        UNWIND $rows AS r
        CREATE (:Manual {id: r.manual_id, title: r.title, device_model: r.device_model,
                         document_type: r.document_type, version: r.version,
                         source_path: r.source_path})
    """, rows=manuals)

    tx.run("""
        UNWIND $rows AS r
        MATCH (m:Manual {id: r.manual_id})
        CREATE (t:ThresholdSpec {id: r.id, scope: r.scope, device_model: r.device_model,
                                 sensor_type: r.sensor_type, metric: r.metric, unit: r.unit,
                                 normal_min: r.normal_min, normal_max: r.normal_max,
                                 warning_min: r.warning_min, critical_min: r.critical_min,
                                 operating_mode: r.operating_mode,
                                 source_section: r.source_section, source_text: r.source_text,
                                 confidence: r.confidence,
                                 validated_by_human: r.validated_by_human})
        CREATE (m)-[:DEFINES_THRESHOLD]->(t)
    """, rows=specs)

    # Device-scope specs attach to every device of that model; the device also
    # links to the manual that defines them.
    tx.run("""
        MATCH (d:Device), (t:ThresholdSpec {scope: 'device'})
        WHERE d.model = t.device_model
        CREATE (d)-[:HAS_THRESHOLD]->(t)
    """)
    tx.run("""
        MATCH (d:Device), (m:Manual)
        WHERE d.model = m.device_model
        MERGE (d)-[:HAS_MANUAL]->(m)
    """)

    # Zone-scope (HSE) specs apply to every zone.
    tx.run("""
        MATCH (z:Zone), (t:ThresholdSpec {scope: 'zone'})
        CREATE (z)-[:HAS_ENV_THRESHOLD]->(t)
    """)

    # ── Device-to-Device and Zone-to-Zone Connectivity ─────────────────────
    # Spatial connectivity between rooms and corridor
    tx.run("""
        MATCH (r1:Zone {id: 'room_1'}), (c1:Zone {id: 'corridor'}), (r2:Zone {id: 'room_2'})
        MERGE (r1)-[:CONNECTS_TO]->(c1)
        MERGE (r2)-[:CONNECTS_TO]->(c1)
    """)

    # Functional dependency relationships between equipment
    tx.run("""
        MATCH (panel:Device {id: 'panel_01'})
        MATCH (pump:Device {id: 'pump_01'})
        MATCH (comp:Device {id: 'compressor_01'})
        MATCH (wh:Device {id: 'wellhead_01'})
        MERGE (panel)-[:CONTROLS]->(pump)
        MERGE (panel)-[:CONTROLS]->(comp)
        MERGE (panel)-[:CONTROLS]->(wh)
        MERGE (pump)-[:FEEDS]->(wh)
        MERGE (comp)-[:SUPPLIES_AIR_TO]->(panel)
    """)

    tx.run("UNWIND $rows AS r CREATE (:Symptom {type: r.type, condition: r.condition})",
           rows=symptoms)

    # Device failure modes (from device manuals).
    tx.run("""
        UNWIND $rows AS r
        CREATE (f:FailureMode {id: r.id, name: r.name, level: 'device', device_model: r.model})
        CREATE (a:Action {id: r.id + '_action', name: r.action})
        CREATE (f)-[:REQUIRES_ACTION]->(a)
        WITH f, r
        MATCH (d:Device {model: r.model})
        CREATE (d)-[:CAN_EXPERIENCE]->(f)
        WITH DISTINCT f, r
        UNWIND r.symptoms AS st
        MATCH (s:Symptom {type: st})
        CREATE (f)-[:INDICATED_BY]->(s)
    """, rows=device_fms)

    # Area/HSE failure modes (from HSE-2025-04) — linked to every zone.
    tx.run("""
        UNWIND $rows AS r
        CREATE (f:FailureMode {id: r.id, name: r.name, level: 'zone', device_model: null})
        CREATE (a:Action {id: r.id + '_action', name: r.action})
        CREATE (f)-[:REQUIRES_ACTION]->(a)
        WITH f, r
        MATCH (z:Zone)
        CREATE (z)-[:CAN_EXPERIENCE]->(f)
        WITH DISTINCT f, r
        UNWIND r.symptoms AS st
        MATCH (s:Symptom {type: st})
        CREATE (f)-[:INDICATED_BY]->(s)
    """, rows=ZONE_FAILURE_MODES)

    logging.info("Topology created: %d devices, %d sensors, %d threshold specs, "
                 "%d device failure modes, %d area failure modes.",
                 len(devices), len(sensors), len(specs), len(device_fms), len(ZONE_FAILURE_MODES))


def main():
    driver = None
    try:
        uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        user = os.environ.get("NEO4J_USER", "neo4j")
        password = os.environ.get("NEO4J_PASSWORD", "rigvision_neo4j")

        driver = GraphDatabase.driver(uri, auth=(user, password))
        driver.verify_connectivity()
        logging.info("Connected to Neo4j successfully.")

        payload = build_payload()
        with driver.session() as session:
            for c in CONSTRAINTS:
                session.run(c)
            session.execute_write(create_topology, payload)

    except ServiceUnavailable as e:
        logging.error(f"Failed to connect to Neo4j. Is the Docker container running? Error: {e}")
    finally:
        if driver is not None:
            driver.close()


if __name__ == "__main__":
    main()
