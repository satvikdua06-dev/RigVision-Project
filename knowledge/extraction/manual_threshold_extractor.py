"""Offline manual-derived threshold extraction.

Reads device manuals (knowledge/documents/ONGC_Device_Manuals.txt), asks the
local LLM (LM Studio, OpenAI-compatible REST — same setup as diagnostic_agent)
to extract structured operating limits, and writes candidate ThresholdSpec
records for human review.

Design principle (docs/anomaly-detector-design.md §13): the LLM extracts
thresholds OFFLINE; a human validates them; runtime detection then does a
deterministic lookup. The LLM is never asked "what is the threshold?" live.

Workflow:
  python manual_threshold_extractor.py
      -> writes knowledge/thresholds/threshold_registry.candidates.json
         (every spec has validated_by_human: false)
  A human reviews each candidate against the manual, fixes values if needed,
  sets validated_by_human: true, and merges it into threshold_registry.json.
  Then re-run seed_graph.py and POST /api/thresholds/refresh.

Usage:
  python manual_threshold_extractor.py [--manuals PATH] [--out PATH]
"""

import argparse
import json
import logging
import os
import re

import requests
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_MANUALS = os.path.join(REPO_ROOT, "knowledge", "documents", "ONGC_Device_Manuals.txt")
DEFAULT_OUT = os.path.join(REPO_ROOT, "knowledge", "thresholds", "threshold_registry.candidates.json")

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:1234/v1").rstrip("/")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "lm-studio")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen2.5-7b-instruct-1m")

# Sensor types used by the live pipeline — extracted specs must map onto these.
SENSOR_TYPES = ["temperature", "vibration", "noise", "gas_h2s", "pressure"]

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "specs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "scope": {"type": "string", "enum": ["device", "zone"]},
                    "device_model": {"type": ["string", "null"]},
                    "sensor_type": {"type": "string", "enum": SENSOR_TYPES},
                    "metric": {"type": "string"},
                    "unit": {"type": "string"},
                    "normal_min": {"type": ["number", "null"]},
                    "normal_max": {"type": ["number", "null"]},
                    "warning_min": {"type": ["number", "null"]},
                    "critical_min": {"type": ["number", "null"]},
                    "operating_mode": {"type": ["string", "null"]},
                    "source_text": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["scope", "device_model", "sensor_type", "metric", "unit",
                             "normal_min", "normal_max", "warning_min", "critical_min",
                             "operating_mode", "source_text", "confidence"],
            },
        }
    },
    "required": ["specs"],
}

PROMPT_TEMPLATE = """You are an engineering-document parser. Extract every numeric operating
limit from the manual section below into structured threshold records.

Rules:
- sensor_type must be one of: {sensor_types}. "H2S" / "gas concentration" -> gas_h2s.
- "Alarm" / "Warning" level -> warning_min. "Trip" / "Shutdown" / "Critical" /
  "Evacuation" level -> critical_min. The stated normal operating range -> normal_min/normal_max.
- scope is "device" if the limit belongs to a specific equipment model (set device_model
  to the exact model string from the section), or "zone" if it is an area/ambient/personnel
  safety limit (set device_model to null).
- metric: a short snake_case name for what is measured (e.g. fluid_end_temperature).
- source_text: quote the exact sentence(s) the numbers came from, verbatim.
- confidence: 0.0-1.0, how certain you are the numbers are correctly transcribed.
- Only extract limits explicitly stated in the text. Never invent values.

MANUAL SECTION ({section_title}):
{section_text}
"""


def split_sections(text: str):
    """Split the manuals file on '--- TITLE ---' headers -> [(title, body), ...]."""
    parts = re.split(r"^---\s*(.+?)\s*---\s*$", text, flags=re.MULTILINE)
    sections = []
    for i in range(1, len(parts) - 1, 2):
        title, body = parts[i].strip(), parts[i + 1].strip()
        if len(body) > 20:
            sections.append((title, body))
    return sections


def extract_from_section(title: str, body: str) -> list:
    prompt = PROMPT_TEMPLATE.format(
        sensor_types=", ".join(SENSOR_TYPES), section_title=title, section_text=body
    )
    resp = requests.post(
        f"{LLM_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": "You extract engineering limits from manuals. "
                                              "Respond with ONLY a single valid JSON object."},
                {"role": "user", "content": prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "threshold_specs", "strict": True, "schema": EXTRACTION_SCHEMA},
            },
            "temperature": 0.0,
            "max_tokens": 2048,
        },
        timeout=180,
    )
    resp.raise_for_status()
    return json.loads(resp.json()["choices"][0]["message"]["content"])["specs"]


def main():
    ap = argparse.ArgumentParser(description="Extract threshold candidates from device manuals.")
    ap.add_argument("--manuals", default=DEFAULT_MANUALS)
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()

    with open(args.manuals, "r", encoding="utf-8") as f:
        sections = split_sections(f.read())
    logging.info("Found %d manual sections in %s", len(sections), args.manuals)

    candidates, counters = [], {}
    for title, body in sections:
        logging.info("Extracting limits from: %s", title)
        try:
            specs = extract_from_section(title, body)
        except Exception as e:
            logging.error("Extraction failed for '%s': %s", title, e)
            continue
        for sp in specs:
            model = sp.get("device_model")
            key = (model or "env", sp["sensor_type"])
            counters[key] = counters.get(key, 0) + 1
            slug = re.sub(r"[^a-z0-9]+", "", (model or "env").lower())
            sp_out = {
                "threshold_id": f"thr_{slug}_{sp['sensor_type']}_{counters[key]:03d}",
                "scope": sp["scope"],
                "device_model": model,
                "sensor_type": sp["sensor_type"],
                "metric": sp["metric"],
                "unit": sp["unit"],
                "normal_range": {"min": sp.get("normal_min"), "max": sp.get("normal_max")},
                "warning_min": sp.get("warning_min"),
                "critical_min": sp.get("critical_min"),
                "operating_mode": sp.get("operating_mode"),
                "source": {
                    "manual_id": None,  # filled during human review
                    "section": title,
                    "text": sp.get("source_text", ""),
                },
                "confidence": sp.get("confidence"),
                "validated_by_human": False,
            }
            candidates.append(sp_out)
        logging.info("  -> %d candidate spec(s)", len(specs))

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({
            "description": "LLM-extracted threshold candidates. Review each spec against the "
                           "manual, set validated_by_human: true, and merge into "
                           "threshold_registry.json. Then re-run seed_graph.py and "
                           "POST /api/thresholds/refresh.",
            "generated_by": "manual_threshold_extractor",
            "source_manuals": os.path.relpath(args.manuals, REPO_ROOT),
            "specs": candidates,
        }, f, indent=2, ensure_ascii=False)
    logging.info("Wrote %d candidate specs to %s", len(candidates), args.out)
    logging.info("NEXT: human-review the candidates, then merge validated specs into "
                 "threshold_registry.json and re-seed the graph.")


if __name__ == "__main__":
    main()
