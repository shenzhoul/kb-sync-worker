
import logging
import math
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from google import genai

from src.scraper import ROOT_DIR, ARTICLES_DIR, sync_articles


STATE_DIR = ROOT_DIR / "state"
LOG_DIR = ROOT_DIR / "logs"
STORE_FILE = STATE_DIR / "gemini_store.txt"

MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
CHUNK_SIZE = 400
CHUNK_OVERLAP = 40
POLL_SECONDS = 5


def configure_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    log_file = LOG_DIR / f"sync-{datetime.now():%Y-%m-%d}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
        force=True,
    )
    return log_file


def get_client():
    load_dotenv(ROOT_DIR / ".env")

    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing API key. Set GEMINI_API_KEY or API_KEY."
        )

    return genai.Client(api_key=api_key)


def get_or_create_store(client):
    """Reuse the saved store, or create one when running in a new environment."""
    store_name = os.getenv("GEMINI_FILE_SEARCH_STORE", "").strip()

    if not store_name and STORE_FILE.exists():
        store_name = STORE_FILE.read_text(encoding="utf-8").strip()

    if store_name:
        logging.info("Using File Search store: %s", store_name)
        return store_name

    store = client.file_search_stores.create(
        config={"display_name": "support-kb-demo"}
    )
    store_name = store.name

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STORE_FILE.write_text(store_name, encoding="utf-8")

    logging.info("Created File Search store: %s", store_name)
    return store_name


def estimate_tokens(text):
    """Rough estimate for logging; not an exact model tokenizer."""
    return len(re.findall(r"\w+|[^\w\s]", text, flags=re.UNICODE))


def estimate_chunks(text):
    tokens = estimate_tokens(text)
    if tokens == 0:
        return 0
    if tokens <= CHUNK_SIZE:
        return 1
    return math.ceil(
        (tokens - CHUNK_OVERLAP) / (CHUNK_SIZE - CHUNK_OVERLAP)
    )


def wait_for_operation(client, operation):
    while not operation.done:
        time.sleep(POLL_SECONDS)
        operation = client.operations.get(operation)

    if getattr(operation, "error", None):
        raise RuntimeError(f"Gemini upload failed: {operation.error}")

    return operation


def remove_existing_document(client, store_name, filename):
    """Delete the previous indexed copy before uploading the replacement."""
    matches = []

    for document in client.file_search_stores.documents.list(
        parent=store_name
    ):
        if getattr(document, "display_name", "") == filename:
            matches.append(document)

    for document in matches:
        logging.info("Removing previous indexed copy: %s", filename)
        client.file_search_stores.documents.delete(
            name=document.name,
            config={"force": True},
        )


def upload_changed_file(client, store_name, change):
    filename = change["filename"]
    path = ARTICLES_DIR / filename

    if not path.is_file():
        raise FileNotFoundError(f"Markdown file not found: {path}")

    content = path.read_text(encoding="utf-8")
    estimated_chunks = estimate_chunks(content)

    remove_existing_document(client, store_name, filename)

    logging.info(
        "Uploading %s (%d estimated chunks)",
        filename,
        estimated_chunks,
    )

    operation = client.file_search_stores.upload_to_file_search_store(
        file=str(path),
        file_search_store_name=store_name,
        config={
            "display_name": filename,
            "chunking_config": {
                "white_space_config": {
                    "max_tokens_per_chunk": CHUNK_SIZE,
                    "max_overlap_tokens": CHUNK_OVERLAP,
                }
            },
        },
    )

    wait_for_operation(client, operation)
    logging.info("UPLOAD OK: %s", filename)

    return estimated_chunks


def main():
    log_file = configure_logging()
    logging.info("=== Knowledge Base Sync started ===")
    logging.info("Log file: %s", log_file)

    client = get_client()
    store_name = get_or_create_store(client)

    sync_result = sync_articles()
    changes = sync_result["changes"]

    uploaded = 0
    estimated_chunks = 0

    for change in changes:
        estimated_chunks += upload_changed_file(
            client, store_name, change
        )
        uploaded += 1

    logging.info(
        "Final summary: discovered=%d added=%d updated=%d "
        "skipped=%d uploaded=%d estimated_chunks=%d",
        sync_result["discovered"],
        sync_result["added"],
        sync_result["updated"],
        sync_result["skipped"],
        uploaded,
        estimated_chunks,
    )
    logging.info("=== Knowledge Base Sync completed successfully ===")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        logging.exception("Sync failed")
        sys.exit(1)
