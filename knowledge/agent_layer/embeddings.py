"""Local embeddings via LM Studio (OpenAI-compatible /v1/embeddings).

Replaces the Gemini embedding calls so RAG retrieval has no external dependency.
Both the offline ingestion (rag_ingestion.py) and the runtime query
(diagnostic_agent.retrieve_manuals) MUST use the same model — the ChromaDB
collection stores vectors of one dimensionality, so switching the model requires
re-running rag_ingestion.py to rebuild the `device_manuals` collection.

Config (see .env.example): EMBED_BASE_URL / EMBED_API_KEY / EMBED_MODEL.
Defaults fall back to the generation LLM's endpoint (same LM Studio server).
"""

import os

import requests
from dotenv import load_dotenv

load_dotenv()

EMBED_BASE_URL = os.environ.get(
    "EMBED_BASE_URL", os.environ.get("LLM_BASE_URL", "http://localhost:1234/v1")
).rstrip("/")
EMBED_API_KEY = os.environ.get("EMBED_API_KEY", os.environ.get("LLM_API_KEY", "lm-studio"))
EMBED_MODEL = os.environ.get("EMBED_MODEL", "text-embedding-nomic-embed-text-v1.5")


def embed_texts(texts, timeout: int = 120):
    """Embed a list of strings in ONE request. Returns a list of float vectors,
    ordered to match the input."""
    if not texts:
        return []
    resp = requests.post(
        f"{EMBED_BASE_URL}/embeddings",
        headers={"Authorization": f"Bearer {EMBED_API_KEY}", "Content-Type": "application/json"},
        json={"model": EMBED_MODEL, "input": texts},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = sorted(resp.json()["data"], key=lambda d: d["index"])
    return [d["embedding"] for d in data]


def embed_text(text: str, timeout: int = 120):
    """Embed a single string -> one float vector."""
    return embed_texts([text], timeout=timeout)[0]
