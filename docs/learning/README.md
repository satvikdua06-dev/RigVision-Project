# RigVision Learning Resources

This folder is a guided reading companion for the RigVision-3D codebase. It is written for someone who wants to understand not only what each file does, but also why the code is shaped this way.

Use these notes side by side with the source code. The project changes quickly, so treat line ranges as a reading map rather than a hard API contract.

## Recommended Reading Order

1. `system-workflow.md`
   Start here. It explains the end-to-end data flow from cameras and sensors to Redis, WebSocket, React, Neo4j, ChromaDB, and the LLM diagnostic output.

2. `contracts-and-config.md`
   Read the shared contracts next. Most bugs in distributed student projects come from different modules silently disagreeing about keys, zone IDs, or payload fields.

3. `backend-api.md`
   Explains how FastAPI bridges Redis, Kafka, MJPEG camera frames, and WebSocket updates.

4. `cv-pipeline.md`
   Explains the main computer vision runtime, including demo mode, live camera mode, video mode, Redis writes, identity fusion, and frame publishing.

5. `cv-submodules.md`
   Explains detector, tracker, cross-camera matching, triangulation, calibration, and the bundled BoT-SORT helpers.

6. `frontend.md`
   Explains the React/Zustand/Three.js app, component responsibilities, and how the dashboard renders real-time state.

7. `sensors-and-compliance.md`
   Explains sensor simulation, Kafka-to-Redis ingestion, YAML safety rules, and the compliance engine.

8. `knowledge-and-diagnostics.md`
   Explains Neo4j seeding, anomaly query generation, RAG ingestion, Gemini diagnostic generation, and Kafka diagnostic publishing.

## How To Read Any File In This Project

For each source file, ask four questions:

1. What data does this file receive?
2. What data does this file emit?
3. What state does this file own?
4. What external system does this file depend on?

In RigVision, the most important external boundaries are:

- Redis keys: `rigvision:persons`, `rigvision:zones`, `rigvision:violations:latest`, `rigvision:diagnostics`, and `rigvision:camera:frame:<id>`.
- Kafka topics: `rigvision.sensors`, `rigvision_alerts`, and `rigvision_diagnostics`.
- Browser state: Zustand store in `frontend/src/stores/useRigStore.js`.
- Spatial contracts: X is room length, Y is height/up, Z is room width, all in meters.
- Zone IDs: `zone_a`, `corridor`, `zone_b`, plus floor-1 variants.

## Project Mental Model

RigVision is not one application. It is several small services sharing a live state model:

- CV pipeline writes people and camera JPEG frames.
- Sensor bridge writes zone telemetry.
- Compliance engine reads people and zones, then writes violations.
- Knowledge layer listens for anomaly alerts and writes diagnostics.
- Backend reads Redis and streams a combined state to the frontend.
- Frontend renders the current state as a 3D digital twin plus operational panels.

The architecture deliberately uses Redis as the real-time state hub because it is simple, fast, and easy to inspect during demos.

