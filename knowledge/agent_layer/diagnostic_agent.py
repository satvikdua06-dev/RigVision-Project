"""LLM diagnostic agent.

Retrieval-augmented root-cause diagnosis for flagged zones. Both RAG retrieval
embeddings AND answer generation run LOCALLY via LM Studio (OpenAI-compatible
REST, called with `requests` — no `openai`/`google` SDK). Generation is
configured by LLM_BASE_URL / LLM_API_KEY / LLM_MODEL; embeddings by
EMBED_BASE_URL / EMBED_API_KEY / EMBED_MODEL (see .env.example and embeddings.py).
"""

import os
import json
import logging

import requests
import chromadb
from dotenv import load_dotenv

try:  # works whether imported as agent_layer.diagnostic_agent or run in-dir
    from .embeddings import embed_text
except ImportError:
    from embeddings import embed_text

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Answer-generation LLM — local LM Studio (OpenAI-compatible REST).
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:1234/v1").rstrip("/")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "lm-studio")
LLM_MODEL = os.environ.get("LLM_MODEL", "google/gemma-4-12b-qat")

# Strict schema for the diagnosis the local model must return.
# `anomaly_detected` is the anti-hallucination gate: the model must set it false (and
# return a "No issue detected" diagnosis) if the telemetry is actually within limits.
DIAGNOSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "anomaly_detected": {"type": "boolean"},
        "primary_diagnosis": {"type": "string"},
        "confidence_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "reasoning": {"type": "string"},
        "recommended_action": {"type": "string"},
    },
    "required": ["anomaly_detected", "primary_diagnosis", "confidence_score",
                 "reasoning", "recommended_action"],
}


class LLMDiagnosticAgent:
    def __init__(self, api_key: str = None):
        # api_key kept for backwards-compat with existing callers; unused now that
        # embeddings are local (see embeddings.py).
        self.db_client = chromadb.HttpClient(host='localhost', port=8100)
        self.collection = self.db_client.get_collection(name="device_manuals")

    def retrieve_manuals(self, graph_context: str) -> str:
        # Embed the query with the SAME local model used to ingest the collection.
        query_embedding = embed_text(graph_context)

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=2
        )

        if not results['documents'][0]:
            return "No specific manual instructions found."

        return "\n\n".join(results['documents'][0])

    def generate_report(self, telemetry: dict, graph_context: str) -> str:
        """Convenience wrapper: retrieve manuals then generate. Callers that want to
        report progress between the two stages call retrieve_manuals() and
        generate_answer() separately (see anomaly_listener)."""
        logging.info("🔍 Retrieving device manuals from Vector DB...")
        manuals_context = self.retrieve_manuals(graph_context)
        return self.generate_answer(telemetry, graph_context, manuals_context)

    def generate_answer(self, telemetry: dict, graph_context: str, manuals_context: str) -> str:
        prompt = f"""
        You are a Senior Lead Reliability and Operations Engineer at RigVision, acting as an automated industrial safety diagnostic engine.
        Your task is to perform a high-fidelity root-cause analysis (RAG & FMEA style) for the active anomaly telemetry, grounded in the facility's knowledge graph topology and official operation manuals.

        [LIVE TELEMETRY SNAPSHOT]
        {json.dumps(telemetry, indent=2)}

        [NEO4J KNOWLEDGE GRAPH TOPOLOGY]
        {graph_context}

        [OFFICIAL DEVICE MANUALS (RAG CONTEXT)]
        {manuals_context}

        DIAGNOSTIC ANALYSIS INSTRUCTIONS:
        1. **Engineering Precision**: Reference specific sensor values, units, and the exact operating limits (warning/critical) stated in the manuals or threshold contexts.
        2. **FMEA & Negative Reasoning**: Detail the exact mechanical or electrical cause-and-effect chain. Use negative reasoning to explicitly justify why you chose the primary diagnosis over other potential failure modes (e.g., explaining why a high vibration reading alone indicates bearing wear rather than motor burnout because the casing temperature remained normal).
        3. **Manual Documentation Alignment**: Cite the exact Document Name, Version, and Section (e.g., "Section 5.6 of ACME-COMP-2200 Rig Air Compressor Manual, rev2") corresponding to the diagnosed failure mode.
        4. **Mitigation Protocol structure**:
           - **Phase 1: Immediate Safety & Isolation**: Detail the exact steps to isolate the equipment. Include electrical LOTO (Lock-Out/Tag-Out), breaker locations, and manual valve isolation sequence.
           - **Phase 2: Remediation & Mechanical Repair**: Provide detailed, step-by-step teardown, cleaning, inspection, and replacement procedures as outlined in the manuals.
           - **Phase 3: Post-Maintenance Verification & Restart**: List the precise criteria required to return the asset to service safely (e.g., temperature/vibration recovery checks, gas level checks using portable sniffers, and pressure hold tests).

        IMPORTANT GATE RULES:
        - If `triggered_sensors` is empty, or all active sensor values are fully within normal operational limits, set "anomaly_detected" to false, "primary_diagnosis" to "No issue detected", "confidence_score" to 0, and reasoning/recommended_action to "System normal."
        - Otherwise, set "anomaly_detected" to true and perform full diagnostic reporting.

        Output a single, strictly formatted JSON response matching the following schema:
        {{
            "anomaly_detected": true or false,
            "primary_diagnosis": "Standard Failure Mode Name (e.g., 'Motor Burnout' or 'Annular Seal Leak').",
            "confidence_score": 0-100 (engineering certainty percentage),
            "reasoning": "A highly professional, detailed engineering explanation of the root cause, referencing specific readings, breach directions, limit thresholds, and negative reasoning justifying the exclusion of other modes.",
            "recommended_action": "A step-by-step mitigation protocol. Structure it clearly: \\n\\n1) IMMEDIATE CONTAINMENT & ELECTRICAL/HYDRAULIC ISOLATION: [detailed steps, LOTO, valve closes] \\n\\n2) MECHANICAL REPAIR & REMEDIATION PROCEDURE: [detailed steps from manuals, inspection, seal/part replacements] \\n\\n3) RETURN-TO-SERVICE POST-MAINTENANCE AUDIT: [verification, temperature/vibration bounds checks, startup sequence]"
        }}
        """

        logging.info("🧠 Generating diagnosis via local LLM (%s @ %s)...", LLM_MODEL, LLM_BASE_URL)
        try:
            response = requests.post(
                f"{LLM_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {LLM_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": LLM_MODEL,
                    "messages": [
                        {"role": "system", "content": "You are a Lead Operations and Reliability Engineer at RigVision. Respond only with a single valid JSON object matching the requested schema. Provide highly detailed, professional engineering content without introductory or concluding conversational text."},
                        {"role": "user", "content": prompt},
                    ],
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "diagnosis",
                            "strict": True,
                            "schema": DIAGNOSIS_SCHEMA,
                        },
                    },
                    "temperature": 0.2,
                    "max_tokens": 1200,
                },
                timeout=180,
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logging.error(f"Failed to generate LLM response: {e}")
            return json.dumps({"error": str(e)})
