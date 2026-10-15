
import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai

load_dotenv()

ROOT = Path(__file__).resolve().parent
STORE_FILE = ROOT / "state" / "gemini_store.txt"

SYSTEM_PROMPT = """You are OptiBot, the customer-support bot for OptiSigns.com.
• Tone: helpful, factual, concise.
• Only answer using the uploaded docs.
• Max 5 bullet points; else link to the doc.
• Cite up to 3 "Article URL:" lines per reply."""

QUESTION = "How do I add a YouTube video?"

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise RuntimeError("Missing GEMINI_API_KEY in .env")

if not STORE_FILE.exists():
    raise RuntimeError("Store not found. Run upload_gemini.py first.")

store_name = STORE_FILE.read_text(encoding="utf-8").strip()
client = genai.Client(api_key=api_key)

interaction = client.interactions.create(
    model="gemini-3.1-flash-lite",
    input=f"{SYSTEM_PROMPT}\n\nUser question: {QUESTION}",
    tools=[
        {
            "type": "file_search",
            "file_search_store_names": [store_name],
        }
    ],
)

print("\n" + "=" * 70)
print(f"QUESTION: {QUESTION}")
print("=" * 70)

for step in interaction.steps or []:
    if step.type != "model_output":
        continue

    for block in step.content or []:
        if block.type != "text":
            continue

        print(block.text)

        for annotation in getattr(block, "annotations", None) or []:
            if getattr(annotation, "type", "") != "file_citation":
                continue

            source = getattr(annotation, "source", "") or ""
            file_name = getattr(annotation, "file_name", "") or "Unknown"

            print("\n--- Retrieved source citation ---")
            print(f"File: {file_name}")

            article_url = next(
                (
                    line.split("Article URL:", 1)[1].strip()
                    for line in source.splitlines()
                    if line.strip().startswith("Article URL:")
                ),
                "",
            )

            if article_url:
                print(f"Article URL: {article_url}")

print("\n" + "=" * 70)
