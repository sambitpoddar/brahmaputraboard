"""
STEP 1 — Run this script on YOUR OWN MACHINE (not GitHub Actions).
=================================================================
brahmaputraboard.gov.in blocks GitHub's IP ranges but is reachable
from a normal internet connection.

This script:
  - Crawls brahmaputraboard.gov.in (BFS, up to MAX_PAGES pages)
  - Saves raw page text to data/raw_pages.json
  - You then commit & push data/raw_pages.json to GitHub
  - GitHub Actions picks it up and runs the AI extraction step

Run:
    pip install requests beautifulsoup4
    python scripts/1_scrape_local.py

Output:
    data/raw_pages.json
"""

import json
import re
import time
import logging
import os
from collections import deque
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# ─── Config ────────────────────────────────────────────────────────────────
BASE_URL        = "https://brahmaputraboard.gov.in"
OUTPUT_FILE     = "data/raw_pages.json"
MAX_PAGES       = 120
MIN_TEXT_LEN    = 150
DELAY           = 1.5       # seconds between requests — be polite
REQUEST_TIMEOUT = 15

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

# ─── Session with real browser headers ─────────────────────────────────────
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
})

SKIP_EXT = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".jpg", ".jpeg", ".png", ".gif", ".zip",
    ".rar", ".mp4", ".mp3", ".ppt", ".pptx"
}

# ─── Helpers ───────────────────────────────────────────────────────────────
def is_same_domain(url: str) -> bool:
    return urlparse(url).netloc in ("", urlparse(BASE_URL).netloc)

def normalize_url(url: str, base: str) -> str:
    full = urljoin(base, url)
    return urlparse(full)._replace(fragment="").geturl()

def get_page(url: str) -> BeautifulSoup | None:
    try:
        resp = SESSION.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except requests.exceptions.Timeout:
        log.warning("[TIMEOUT] %s", url)
    except requests.exceptions.ConnectionError:
        log.warning("[CONNECTION ERROR] %s", url)
    except requests.exceptions.HTTPError as e:
        log.warning("[HTTP %s] %s", e.response.status_code, url)
    except Exception as e:
        log.warning("[ERROR] %s — %s", url, e)
    return None

def extract_links(soup: BeautifulSoup, current_url: str) -> list[str]:
    links = []
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        full = normalize_url(href, current_url)
        if is_same_domain(full) and full.startswith("http"):
            links.append(full)
    return links

def extract_text(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "noscript", "iframe", "header", "footer", "nav"]):
        tag.decompose()
    body = (
        soup.find("main")
        or soup.find("article")
        or soup.find(id="content")
        or soup.find(id="main-content")
        or soup.find(class_="content")
        or soup.find(class_="main-content")
        or soup.body
    )
    raw = body.get_text(separator="\n") if body else ""
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()

def extract_title(soup: BeautifulSoup) -> str:
    return soup.title.get_text(strip=True) if soup.title else ""

# ─── Crawl ─────────────────────────────────────────────────────────────────
def crawl() -> list[dict]:
    visited: set[str]   = set()
    queue:   deque[str] = deque([BASE_URL])
    pages:   list[dict] = []

    log.info("Starting crawl of %s (max %d pages)", BASE_URL, MAX_PAGES)

    while queue and len(visited) < MAX_PAGES:
        url = queue.popleft()

        if url in visited:
            continue
        visited.add(url)

        path = urlparse(url).path.lower()
        if any(path.endswith(ext) for ext in SKIP_EXT):
            continue

        log.info("[%3d/%d] %s", len(visited), MAX_PAGES, url)
        soup = get_page(url)

        if soup is None:
            time.sleep(DELAY)
            continue

        text  = extract_text(soup)
        title = extract_title(soup)

        if len(text) >= MIN_TEXT_LEN:
            pages.append({"url": url, "title": title, "text": text})
            log.info("  → stored %d chars", len(text))

        for link in extract_links(soup, url):
            if link not in visited:
                queue.append(link)

        time.sleep(DELAY)

    log.info("Crawl complete: %d pages with content", len(pages))
    return pages

# ─── Main ──────────────────────────────────────────────────────────────────
def main():
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    pages = crawl()

    if not pages:
        log.error("No pages scraped. Check your internet connection.")
        return

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump({"pages": pages, "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, f, ensure_ascii=False, indent=2)

    log.info("Saved %d pages → %s (%.1f KB)", len(pages), OUTPUT_FILE,
             os.path.getsize(OUTPUT_FILE) / 1024)
    log.info("")
    log.info("Next step: commit and push data/raw_pages.json to GitHub.")
    log.info("  git add data/raw_pages.json")
    log.info("  git commit -m 'chore: update raw scraped pages'")
    log.info("  git push")
    log.info("GitHub Actions will pick it up and extract FAQs automatically.")

if __name__ == "__main__":
    main()
