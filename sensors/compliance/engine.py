from __future__ import annotations
import json, logging, os, signal, sys, threading, time, uuid
from typing import Dict, List, Optional
import redis

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("compliance")
shutdown_event = threading.Event()

def signal_handler(sig, frame):
    shutdown_event.set()

signal.signal(signal.SIGINT, signal_handler)

def load_rules(rules_dir: str) -> list[dict]:
    try:
        import yaml
    except ImportError:
        logger.error("pip install pyyaml")
        sys.exit(1)
    if not os.path.isdir(rules_dir): return []
    rules = []
    for fn in os.listdir(rules_dir):
        if fn.endswith((".yaml", ".yml")):
            with open(os.path.join(rules_dir, fn), "r") as f:
                data = yaml.safe_load(f)
                if data and "rules" in data: rules.extend(data["rules"])
    return rules

def evaluate_ppe_rule(rule: dict, persons: list[dict], zones: dict) -> list[dict]:
    viols = []
    req, zones_l = rule.get("required_ppe", []), rule.get("zones")
    for p in persons:
        if zones_l and p.get("zone") not in zones_l: continue
        for item in req:
            if p.get("ppe", {}).get(item) is False:
                viols.append({
                    "id": f"v-{uuid.uuid4().hex[:8]}", "rule_id": rule["id"], "zone": p.get("zone", "unknown"),
                    "severity": rule.get("severity", "MEDIUM"), "message": f"Person #{p['id']} missing {item.replace('_', ' ')}",
                    "person_ids": [p["id"]], "timestamp": int(time.time() * 1000)
                })
    return viols

def evaluate_occupancy_rule(rule: dict, persons: list[dict], zones: dict) -> list[dict]:
    viols, z_counts = [], {}
    max_occ, zones_l = rule.get("max_occupancy", 99), rule.get("zones")
    for p in persons:
        z = p.get("zone", "unknown")
        if zones_l and z not in zones_l: continue
        z_counts.setdefault(z, []).append(p["id"])
    for z, pids in z_counts.items():
        if len(pids) > max_occ:
            viols.append({
                "id": f"v-{uuid.uuid4().hex[:8]}", "rule_id": rule["id"], "zone": z,
                "severity": rule.get("severity", "HIGH"), "message": f"Zone {z} overcrowded: {len(pids)}/{max_occ} persons",
                "person_ids": pids, "timestamp": int(time.time() * 1000)
            })
    return viols

def evaluate_environment_rule(rule: dict, persons: list[dict], zones: dict) -> list[dict]:
    viols = []
    stype, thresh, zones_l = rule.get("sensor_type"), rule.get("threshold"), rule.get("zones")
    if not stype or thresh is None: return viols
    for zid, zdata in zones.items():
        if zones_l and zid not in zones_l: continue
        val = zdata.get(stype, 0)
        if val >= thresh:
            viols.append({
                "id": f"v-{uuid.uuid4().hex[:8]}", "rule_id": rule["id"], "zone": zid,
                "severity": rule.get("severity", "HIGH"), "message": f"{stype} in {zid} = {val:.1f} exceeds threshold ({thresh})",
                "person_ids": [p["id"] for p in persons if p.get("zone") == zid], "timestamp": int(time.time() * 1000)
            })
    return viols

RULE_EVALUATORS = {"ppe": evaluate_ppe_rule, "occupancy": evaluate_occupancy_rule, "environment": evaluate_environment_rule}

def run_engine(redis_host="localhost", redis_port=6379, redis_password=None, rules_dir=None, eval_interval=2.0) -> None:
    rules_dir = rules_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules")
    r_client = redis.Redis(host=redis_host, port=redis_port, password=redis_password or os.getenv("REDIS_PASSWORD"), decode_responses=True)
    r_client.ping()
    rules = load_rules(rules_dir)
    logger.info("Compliance engine started. Evaluating every %.1fs...", eval_interval)
    eval_count = 0

    while not shutdown_event.is_set():
        try:
            p_raw, z_raw = r_client.get("rigvision:persons"), r_client.get("rigvision:zones")
            persons, zones = json.loads(p_raw) if p_raw else [], json.loads(z_raw) if z_raw else {}
            viols = []
            for r in rules:
                evaluator = RULE_EVALUATORS.get(r.get("type", "ppe"))
                if evaluator: viols.extend(evaluator(r, persons, zones))
            r_client.set("rigvision:violations:latest", json.dumps(viols))
            eval_count += 1
            if eval_count % 10 == 0:
                logger.info("Eval #%d: %d violations from %d persons across %d zones", eval_count, len(viols), len(persons), len(zones))
        except redis.ConnectionError:
            time.sleep(2)
        except Exception as e:
            logger.error("Compliance eval error: %s", e)
            time.sleep(1)
        shutdown_event.wait(timeout=eval_interval)

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="RigVision-3D Compliance Engine")
    parser.add_argument("--redis-host", default=os.getenv("REDIS_HOST", "localhost"))
    parser.add_argument("--redis-port", type=int, default=int(os.getenv("REDIS_PORT", "6379")))
    parser.add_argument("--redis-password", default=None)
    parser.add_argument("--rules-dir", default=None)
    parser.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args()
    run_engine(redis_host=args.redis_host, redis_port=args.redis_port, redis_password=args.redis_password, rules_dir=args.rules_dir, eval_interval=args.interval)

if __name__ == "__main__":
    main()
