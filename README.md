# Knowledge Base Sync

A one-shot Python worker that syncs public OptiSigns Help Center articles to Markdown and indexes changed documents in Google Gemini File Search.

## How it works
- Fetches published articles through the Help Center API and converts HTML to Markdown, preserving headings, links, and code.
- Tracks timestamps and SHA-256 hashes in `state/manifest.json`.
- First run indexes up to 30 article bodies and records remaining articles as a metadata baseline. Later runs index only new or changed articles and replace existing indexed documents when needed.
- Logs added, updated, skipped, uploaded, and estimated chunk counts. Gemini File Search handles chunking; configured size is 400 tokens with 40-token overlap. Chunk counts are estimates.

## Run locally

Requires Python 3.12+ and a Gemini API key with File Search access.

```bash
pip install -r requirements.txt
python main.py
```

Configure `GEMINI_API_KEY` in `.env`. Optionally set `GEMINI_FILE_SEARCH_STORE` to reuse a store. Exit code is `0` on success and `1` on failure. Logs are written to `logs/`.

## Run with Docker

```bash
docker build -t kb-sync-worker .
docker run --rm -e API_KEY -e GEMINI_FILE_SEARCH_STORE kb-sync-worker
```

Set both environment variables before running. Mount `state/` and `logs/` for persistence.

## Daily automation

GitHub Actions runs daily and supports manual runs. Configure repository secrets `GEMINI_API_KEY` and `GEMINI_FILE_SEARCH_STORE`. Logs are uploaded as artifacts and retained for seven days.

[View workflow runs and log artifacts](https://github.com/shenzhoul/kb-sync-worker/actions/workflows/daily-sync.yml)

## Assistant test

YouTube Q&A verified with Gemini File Search and a matching source citation. [Screenshot](evidence/optibot-youtube-answer.png)

Never commit `.env` or API keys.