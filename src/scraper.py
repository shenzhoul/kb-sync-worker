
import hashlib
import json
import logging
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from markdownify import markdownify


ROOT_DIR = Path(__file__).resolve().parent.parent
ARTICLES_DIR = ROOT_DIR / "data" / "articles"
MANIFEST_PATH = ROOT_DIR / "state" / "manifest.json"

BASE_URL = "https://support.optisigns.com"
ARTICLES_API = f"{BASE_URL}/api/v2/help_center/articles.json"
INITIAL_LIMIT = 30
REQUEST_TIMEOUT = 30


def make_slug(title: str, article_id: int) -> str:
    slug = title.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "-", slug).strip("-")
    return f"{slug or 'article'}-{article_id}"


def html_to_markdown(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")

    for element in soup.select(
        "script, style, nav, footer, aside, "
        ".breadcrumbs, .article-relatives, "
        ".related-articles, .share, .advertisement"
    ):
        element.decompose()

    markdown = markdownify(
        str(soup),
        heading_style="ATX",
        bullets="-",
    )

    lines = [line.rstrip() for line in markdown.splitlines()]
    markdown = "\n".join(lines)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)

    return markdown.strip()


def fetch_articles(session: requests.Session) -> list[dict]:
    """Fetch all publicly visible article metadata."""
    next_url = f"{ARTICLES_API}?per_page=100"
    articles_by_id = {}

    while next_url:
        response = session.get(next_url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()

        for article in payload.get("articles", []):
            if article.get("draft", False):
                continue
            if not article.get("title") or not article.get("html_url"):
                continue

            articles_by_id[str(article["id"])] = article

        next_url = payload.get("next_page")
        if next_url:
            time.sleep(0.2)

    return list(articles_by_id.values())


def load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        return {}

    try:
        data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError):
        logging.warning("Manifest unreadable; starting a new manifest.")

    return {}


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = MANIFEST_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(MANIFEST_PATH)


def download_markdown(
    session: requests.Session,
    article: dict,
) -> tuple[str, str, str]:
    article_id = article["id"]
    detail_url = (
        f"{BASE_URL}/api/v2/help_center/articles/{article_id}.json"
    )

    response = session.get(detail_url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    full_article = response.json().get("article", article)
    title = full_article.get("title") or article["title"]
    article_url = full_article.get("html_url") or article["html_url"]
    updated_at = full_article.get("updated_at") or article.get("updated_at", "")

    body = html_to_markdown(full_article.get("body", ""))

    document = (
        f"# {title}\n\n"
        f"Article URL: {article_url}\n\n"
        f"Last updated: {updated_at}\n\n"
        f"---\n\n"
        f"{body}\n"
    )

    digest = hashlib.sha256(document.encode("utf-8")).hexdigest()
    filename = make_slug(title, article_id) + ".md"

    return filename, document, digest


def sync_articles() -> dict:
    """Synchronize local Markdown and return changed files for indexing."""
    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": "KnowledgeBaseSync/1.0"})

    logging.info("Fetching Help Center article metadata...")
    articles = fetch_articles(session)
    logging.info("Visible published articles discovered: %d", len(articles))

    old_manifest = load_manifest()
    first_baseline = not old_manifest.get("_baseline_complete", False)

    # On the first integrated run, preserve the existing 30-article
    # scope. Other IDs are recorded as a baseline without downloading
    # their full article bodies.
    existing_ids = {
        key for key in old_manifest.keys() if not key.startswith("_")
    }

    if not old_manifest:
        seed_articles = articles[:INITIAL_LIMIT]
        seed_ids = {str(article["id"]) for article in seed_articles}
    else:
        seed_ids = set()

    manifest = dict(old_manifest)
    changes = []
    counts = {"added": 0, "updated": 0, "skipped": 0}

    for article in articles:
        article_id = str(article["id"])
        title = article["title"].strip()
        updated_at = article.get("updated_at", "")
        previous = old_manifest.get(article_id)

        expected_filename = make_slug(title, article["id"]) + ".md"
        existing_local_file = ARTICLES_DIR / expected_filename

        # Record existing, previously unseen articles as a baseline on
        # the first run, unless a matching Markdown file already exists.
        if (
            first_baseline
            and previous is None
            and article_id not in seed_ids
            and not existing_local_file.exists()
        ):
            manifest[article_id] = {
                "title": title,
                "url": article["html_url"],
                "updated_at": updated_at,
                "filename": None,
                "sha256": None,
                "baseline_only": True,
            }
            counts["skipped"] += 1
            continue

        is_new = previous is None
       
        # Skip baseline-only articles unless their timestamp changes.
        if (
            previous
            and previous.get("baseline_only")
            and previous.get("updated_at", "") == updated_at
        ):
            counts["skipped"] += 1
            continue

        needs_download = (
            is_new
            or previous is None
            or (
                not previous.get("baseline_only")
                and not previous.get("sha256")
            )
            or previous.get("updated_at", "") != updated_at
            or not previous.get("filename")
        )

        if not needs_download:
            counts["skipped"] += 1
            continue

        if not needs_download:
            counts["skipped"] += 1
            continue

        filename, document, digest = download_markdown(session, article)
        output_path = ARTICLES_DIR / filename

        if previous and previous.get("sha256") == digest:
            previous.update({
                "title": title,
                "url": article["html_url"],
                "updated_at": updated_at,
                "filename": filename,
                "baseline_only": False,
            })
            manifest[article_id] = previous
            counts["skipped"] += 1
            continue

        output_path.write_text(document, encoding="utf-8")

        # Remove a previous local filename if the article title changed.
        old_filename = previous.get("filename") if previous else None
        if old_filename and old_filename != filename:
            old_path = ARTICLES_DIR / old_filename
            if old_path.exists():
                old_path.unlink()

        action = "added" if is_new else "updated"
        counts[action] += 1

        manifest[article_id] = {
            "title": title,
            "url": article["html_url"],
            "updated_at": updated_at,
            "filename": filename,
            "sha256": digest,
            "baseline_only": False,
        }

        changes.append({
            "article_id": article_id,
            "action": action,
            "filename": filename,
            "sha256": digest,
        })

        logging.info("%s: %s", action.upper(), filename)

    manifest["_baseline_complete"] = True
    save_manifest(manifest)

    result = {
        "discovered": len(articles),
        "added": counts["added"],
        "updated": counts["updated"],
        "skipped": counts["skipped"],
        "changes": changes,
    }

    logging.info(
        "Local sync summary: discovered=%d added=%d updated=%d skipped=%d",
        result["discovered"],
        result["added"],
        result["updated"],
        result["skipped"],
    )

    return result


def scrape() -> int:
    """Compatibility entry point for running the scraper by itself."""
    result = sync_articles()
    return result["added"] + result["updated"]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    scrape()
