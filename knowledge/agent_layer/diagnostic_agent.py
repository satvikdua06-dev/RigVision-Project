import os
import json
import logging
import chromadb
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class LLMDiagnosticAgent:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is missing!")
        
        self.client = genai.Client(api_key=self.api_key)
        self.model_name = 'gemini-2.5-flash'
        
        self.db_client = chromadb.HttpClient(host='localhost', port=8100)
        self.collection = self.db_client.get_collection(name="device_manuals")

    def retrieve_manuals(self, graph_context: str) -> str:
        query_embedding = self.client.models.embed_content(
            model='gemini-embedding-001',
            contents=graph_context
        ).embeddings[0].values
        
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=2
        )
        
        if not results['documents'][0]:
            return "No specific manual instructions found."
            
        return "\n\n".join(results['documents'][0])

    def generate_report(self, telemetry: dict, graph_context: str) -> str:
        logging.info("🔍 Retrieving device manuals from Vector DB...")
        manuals_context = self.retrieve_manuals(graph_context)
        
        prompt = f"""
        You are an elite Industrial Safety AI acting as a diagnostic engine.
        Your task is to analyze real-time anomaly telemetry alongside the structural knowledge graph 
        of the facility and the official device manuals. Use negative reasoning.
        
        [LIVE TELEMETRY]
        {json.dumps(telemetry, indent=2)}
        
        [KNOWLEDGE GRAPH TOPOLOGY]
        {graph_context}
        
        [DEVICE MANUALS (RAG CONTEXT)]
        {manuals_context}
        
        Output a strictly formatted JSON response using this exact schema:
        {{
            "primary_diagnosis": "Name of the highest probability failure mode.",
            "confidence_score": 0-100,
            "reasoning": "A concise explanation of why this failure was chosen over others.",
            "recommended_action": "A highly detailed, step-by-step emergency response protocol and mitigation procedure. Include: 1) Immediate safety precautions (e.g., lock-out/tag-out, power isolation, evacuation thresholds), 2) Core repair instructions derived from the device manuals (e.g., lubricating bearings, inspecting for micro-fractures, replacing the specific component), and 3) Post-maintenance verification checks (e.g., monitoring temperature/vibration recovery, checking gas PPM levels)."
        }}
        """
        
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                )
            )
            return response.text
        except Exception as e:
            logging.error(f"Failed to generate LLM response: {e}")
            return json.dumps({"error": str(e)})