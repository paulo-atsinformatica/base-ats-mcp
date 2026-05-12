from google import genai
import os
from dotenv import load_dotenv

load_dotenv()

client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

print("Listing embedding models:")
for model in client.models.list():
    if "embedContent" in model.supported_methods:
        print(f" - {model.name}")
