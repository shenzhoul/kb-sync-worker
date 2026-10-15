
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai

load_dotenv()

ROOT = Path(__file__).resolve().parent
ARTICLES_DIR = ROOT / "data" / "articles"
STORE_ID_FILE = ROOT / "state" / "gemini_store.txt"

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise RuntimeError("Missing GEMINI_API_KEY in .env")

files = sorted(ARTICLES_DIR.glob("*.md"))
if len(files) < 30:
    raise RuntimeError(
        f"Expected at least 30 Markdown files; found {len(files)}"
    )

client = genai.Client(api_key=api_key)

# Reuse an existing store if one has already been created.
if STORE_ID_FILE.exists():
    store_name = STORE_ID_FILE.read_text(encoding="utf-8").strip()
    store = client.file_search_stores.get(name=store_name)
    print(f"Reusing store: {store.name}")
else:
    store = client.file_search_stores.create(
        config={
            "display_name": "support-kb-demo",
            "embedding_model": "models/gemini-embedding-2",
        }
    )
    STORE_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
    STORE_ID_FILE.write_text(store.name, encoding="utf-8")
    print(f"Created store: {store.name}")

uploaded = 0

for path in files:
    print(f"Uploading ({uploaded + 1}/{len(files)}): {path.name}")

    operation = client.file_search_stores.upload_to_file_search_store(
        file=str(path),
        file_search_store_name=store.name,
        config={
            "display_name": path.name,
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
        raise RuntimeError(
            f"Upload failed for {path.name}: {operation.error}"
        )

    uploaded += 1
    print(f"Indexed: {path.name}")

print(f"\nFinished. Files submitted and indexed: {uploaded}")
print(f"File Search store: {store.name}")
print(f"Store ID saved to: {STORE_ID_FILE}")
