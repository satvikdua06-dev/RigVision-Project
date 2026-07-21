"""Ingest OISD/DGMS/Factory Act regulations into ChromaDB `regulatory_corpus` collection.

Uses the SAME local embedding model as device_manuals so both collections
can be queried together in the diagnostic pipeline.

Usage:
  python knowledge/agent_layer/regulatory_ingest.py
"""

import os
from pathlib import Path

import chromadb

try:
    from .embeddings import embed_texts, EMBED_MODEL
except ImportError:
    from embeddings import embed_texts, EMBED_MODEL

_HERE = Path(__file__).resolve().parent
DOCS_DIR = _HERE.parent / "documents"
CHROMA_HOST = os.getenv("CHROMADB_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMADB_PORT", "8100"))
COLLECTION  = "regulatory_corpus"

print(f"Connecting to ChromaDB at {CHROMA_HOST}:{CHROMA_PORT}...")
client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)

try:
    client.delete_collection(name=COLLECTION)
    print(f"Deleted existing '{COLLECTION}' collection.")
except Exception:
    pass

collection = client.create_collection(name=COLLECTION)
print(f"Created '{COLLECTION}' collection.")


def ingest_file(filepath: Path) -> int:
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    chunks = [c.strip() for c in content.split("---") if len(c.strip()) > 30]
    if not chunks:
        return 0
    print(f"Embedding {len(chunks)} chunks from {filepath.name} with '{EMBED_MODEL}'...")
    embeddings = embed_texts(chunks)
    ids = [f"{filepath.stem}_{i}" for i in range(len(chunks))]
    metadatas = [{"source": filepath.name, "chunk_index": i} for i in range(len(chunks))]
    collection.add(documents=chunks, embeddings=embeddings, ids=ids, metadatas=metadatas)
    print(f"  Ingested {len(chunks)} chunks from {filepath.name}")
    return len(chunks)


total = 0
for doc_file in [DOCS_DIR / "OISD_DGMS_Regulations.txt"]:
    if doc_file.exists():
        total += ingest_file(doc_file)
    else:
        print(f"  WARNING: {doc_file} not found — skipping.")

print(f"\nRegulatory RAG ingestion complete. {total} total chunks in '{COLLECTION}'.")
