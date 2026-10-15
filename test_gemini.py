
import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise RuntimeError("Missing GEMINI_API_KEY in .env")

client = genai.Client(api_key=api_key)

interaction = client.interactions.create(
    model="gemini-3.1-flash-lite",
    input="Reply with exactly: GEMINI_API_OK",
)

print(interaction.output_text)
