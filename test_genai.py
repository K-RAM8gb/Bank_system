import os
from google import genai
from google.genai import types

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", "dummy"))
try:
    config = types.GenerateContentConfig(response_mime_type="application/json")
    print("Config created successfully!")
except Exception as e:
    print(f"Error: {e}")
