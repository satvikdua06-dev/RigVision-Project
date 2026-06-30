import os
import chromadb
from google import genai
from dotenv import load_dotenv

load_dotenv()

api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    raise ValueError("GEMINI_API_KEY is not set!")

client = genai.Client(api_key=api_key)

print("Connecting to ChromaDB Docker container on port 8100...")
db_client = chromadb.HttpClient(host='localhost', port=8100)

try:
    db_client.delete_collection(name="device_manuals")
except Exception:
    pass 

collection = db_client.create_collection(name="device_manuals")

def ingest_manuals(filepath):
    with open(filepath, 'r') as file:
        content = file.read()
    
    chunks = [chunk.strip() for chunk in content.split("---") if len(chunk.strip()) > 20]
    
    embeddings = []
    ids = []
    
    for i, chunk in enumerate(chunks):
        response = client.models.embed_content( model='gemini-embedding-001', contents=chunk)
        embeddings.append(response.embeddings[0].values)
        ids.append(f"doc_{i}")
        
    collection.add(documents=chunks, embeddings=embeddings, ids=ids)
    print("RAG Ingestion Complete!")

if __name__ == "__main__":
    current_dir = os.path.dirname(os.path.abspath(__file__))
    document_path = os.path.join(current_dir, "..", "documents", "ONGC_Device_Manuals.txt")
    ingest_manuals(document_path)