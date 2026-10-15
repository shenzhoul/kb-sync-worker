
import os
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from markdownify import markdownify
from dotenv import load_dotenv
from google import genai

load_dotenv()

ROOT = Path(__file__).resolve().parent
ARTICLE_ID = 360051014713
ARTICLE_URL = (
    "https://support.optisigns.com/hc/en-us/articles/"
    "360051014713-How-to-Use-YouTube-with-OptiSigns"
)
STORE_FILE = ROOT / "state" / "gemini_store.txt"
OUTPUT = ROOT / "data" / "articles" / "how-to-use-youtube-with-optisigns.md"

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise RuntimeError("Missing GEMINI_API_KEY in .env")

store_name = STORE_FILE.read_text(encoding="utf-8").strip()
client = genai.Client(api_key=api_key)

api_url = (
    f"https://support.optisigns.com/api/v2/help_center/"
    f"articles/{ARTICLE_ID}.json"
)
response = requests.get(api_url, timeout=30)
response.raise_for_status()

article = response.json()["article"]
soup = BeautifulSoup(article.get("body") or "", "html.parser")

for element in soup.select("script, style, nav, footer, aside"):
    element.decompose()

body = markdownify(str(soup), heading_style="ATX", bullets="-")
body = "\n".join(line.rstrip() for line in body.splitlines())

document = (
    f"# {article['title']}\n\n"
    f"Article URL: {ARTICLE_URL}\n\n"
    f"Last updated: {article.get('updated_at', '')}\n\n"
    f"---\n\n{body.strip()}\n"
)

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
OUTPUT.write_text(document, encoding="utf-8")
print(f"Saved article: {OUTPUT.name}")

operation = client.file_search_stores.upload_to_file_search_store(
    file=str(OUTPUT),
    file_search_store_name=store_name,
    config={
        "display_name": OUTPUT.name,
        "chunking_config": {
            "white_space_config": {
                "max_tokens_per_chunk": 400,
                "max_overlap_tokens": 40,
            }
        },
    },
)

while not operation.done:
    time.sleep(5)
    operation = client.operations.get(operation)

if getattr(operation, "error", None):
    raise RuntimeError(f"Indexing failed: {operation.error}")

print("YouTube article indexed successfully.")
print(f"Store: {store_name}")
