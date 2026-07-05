"""Ingest device manuals into the ChromaDB `device_manuals` collection.

Embeddings are generated LOCALLY via LM Studio (see embeddings.py) — the SAME
model the diagnostic agent uses at query time. Re-run this whenever the manuals
change OR the embedding model changes (the collection is recreated each run).

Usage:
  python knowledge/agent_layer/rag_ingestion.py
"""

import os

import chromadb
from dotenv import load_dotenv

try:  # works whether run in-dir or imported as agent_layer.rag_ingestion
    from .embeddings import embed_texts, EMBED_MODEL
except ImportError:
    from embeddings import embed_texts, EMBED_MODEL

load_dotenv()

print("Connecting to ChromaDB Docker container on port 8100...")
db_client = chromadb.HttpClient(host='localhost', port=8100)

try:
    db_client.delete_collection(name="device_manuals")
except Exception:
    pass

collection = db_client.create_collection(name="device_manuals")


def ingest_manuals(filepath):
    with open(filepath, 'r', encoding='utf-8') as file:
        content = file.read()

    chunks = [chunk.strip() for chunk in content.split("---") if len(chunk.strip()) > 20]
    if not chunks:
        print("No chunks found to ingest.")
        return

    # One batched embeddings request for all chunks instead of N round-trips.
    print(f"Embedding {len(chunks)} chunks with '{EMBED_MODEL}'...")
    embeddings = embed_texts(chunks)
    ids = [f"doc_{i}" for i in range(len(chunks))]

    collection.add(documents=chunks, embeddings=embeddings, ids=ids)
    print(f"RAG Ingestion Complete! ({len(chunks)} chunks)")


if __name__ == "__main__":
    current_dir = os.path.dirname(os.path.abspath(__file__))
    document_path = os.path.join(current_dir, "..", "documents", "ONGC_Device_Manuals.txt")
    ingest_manuals(document_path)
