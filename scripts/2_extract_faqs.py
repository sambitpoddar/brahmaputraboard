"""
STEP 2 — Runs automatically on GitHub Actions.
==============================================
This script does NOT touch the internet for scraping.
It reads data/raw_pages.json (committed by you from your local machine),
sends each page's text to Cerebras AI, deduplicates, and writes faqs.json.

Triggered by:
  - Push to main branch when data/raw_pages.json changes
  - Manual workflow_dispatch from GitHub Actions UI

Requirements (installed by GitHub Actions):
    pip install cerebras-cloud-sdk
"""

import os
import json
import re
import time
import hashlib
import logging
from datetime import datetime, timezone

from cerebras.cloud.sdk import Cerebras

# ─── Config ────────────────────────────────────────────────────────────────
INPUT_FILE     = "data/raw_pages.json"
OUTPUT_FILE    = "data/faqs.json"
MODEL          = "qwen-3-235b-a22b-instruct-2507"
SIMILARITY_THR = 0.52
CEREBRAS_KEY   = os.environ["CEREBRAS_API_KEY"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

# ─── Cerebras client ───────────────────────────────────────────────────────
client = Cerebras(api_key=CEREBRAS_KEY)

EXTRACT_PROMPT = """\
You are an information extraction assistant for the Brahmaputra Board,
a Government of India statutory body under the Ministry of Jal Shakti.

From the webpage text below, extract FAQ pairs genuinely useful to citizens,
contractors, researchers, or government officials.

STRICT RULES:
- Extract ONLY factual information explicitly present in the text.
- Do NOT invent, infer, or hallucinate any detail whatsoever.
- Each answer must be self-contained (makes sense without reading the question).
- Questions must be natural queries a real user would type.
- Prioritise: contact details, dates, names, project info, procedures, deadlines.
- For each fact, generate 3–4 differently phrased questions that all mean the same thing.
  Example: "Who is the Chairman?", "Name of the chairman", "Current chairman of Brahmaputra Board", "Who heads the Brahmaputra Board?"
- Return ONLY valid JSON — an array of objects with keys "question" and "answer".
- If the page has no FAQ-worthy content, return exactly: []
- Do NOT wrap output in markdown code fences.

EXAMPLE:
[
  {{
    "question": "Who is the Chairman of the Brahmaputra Board?",
    "answer": "The Chairman of the Brahmaputra Board is Dr. Ranbir Singh, IAS (R)."
  }}
]

PAGE TITLE: {title}

WEBPAGE TEXT:
\"\"\"
{text}
\"\"\"
"""

def extract_faqs(url: str, title: str, text: str) -> list[dict]:
    """Call Cerebras to extract structured FAQ pairs from one page."""
    # Keep first 3500 + last 1500 chars for token budget
    if len(text) > 5500:
        text = text[:3500] + "\n\n[...truncated...]\n\n" + text[-1500:]

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{
                "role": "user",
                "content": EXTRACT_PROMPT.format(title=title, text=text)
            }],
            max_completion_tokens=1800,
            temperature=0.1,
        )
        raw = resp.choices[0].message.content.strip()

        # Strip accidental markdown fences
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\s*```\s*$",       "", raw, flags=re.MULTILINE)

        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            return []

        result = []
        for item in parsed:
            q = str(item.get("question", "")).strip()
            a = str(item.get("answer",   "")).strip()
            if len(q) > 8 and len(a) > 12:
                result.append({"question": q, "answer": a, "source": url})

        log.info("  → %d FAQs extracted", len(result))
        return result

    except json.JSONDecodeError as e:
        log.warning("JSON parse error for %s: %s", url, e)
        return []
    except Exception as e:
        log.warning("Cerebras error for %s: %s", url, e)
        return []

# ─── Deduplication ─────────────────────────────────────────────────────────
def tokenize(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", s.lower()))

def jaccard(a: str, b: str) -> float:
    ta, tb = tokenize(a), tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)

def faq_id(q: str) -> str:
    return hashlib.md5(q.strip().lower().encode()).hexdigest()[:12]

def deduplicate(existing: list[dict], candidates: list[dict]) -> tuple[list[dict], int, int]:
    merged   = list(existing)
    added    = 0
    skipped  = 0

    existing_qs  = [e["question"] for e in merged]
    existing_ids = {faq_id(q) for q in existing_qs}

    for cand in candidates:
        cq  = cand["question"]
        cid = faq_id(cq)

        if cid in existing_ids:
            skipped += 1
            continue

        if any(jaccard(cq, eq) >= SIMILARITY_THR for eq in existing_qs):
            skipped += 1
            continue

        cand["id"]       = cid
        cand["added_at"] = datetime.now(timezone.utc).isoformat()
        merged.append(cand)
        existing_qs.append(cq)
        existing_ids.add(cid)
        added += 1

    return merged, added, skipped

# ─── Main ──────────────────────────────────────────────────────────────────
def main():
    log.info("═══ FAQ Extractor — %s UTC ═══",
             datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"))

    # Load raw scraped pages
    if not os.path.exists(INPUT_FILE):
        log.error("%s not found. Run scripts/1_scrape_local.py on your machine first.", INPUT_FILE)
        raise SystemExit(1)

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    pages = data.get("pages", [])
    scraped_at = data.get("scraped_at", "unknown")
    log.info("Loaded %d pages (scraped at %s)", len(pages), scraped_at)

    # Load existing FAQs
    existing: list[dict] = []
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f).get("faqs", [])
            log.info("Loaded %d existing FAQs", len(existing))
        except (json.JSONDecodeError, KeyError):
            log.warning("faqs.json malformed — starting fresh")

    # Extract FAQs via Cerebras
    all_candidates: list[dict] = []
    for i, page in enumerate(pages, 1):
        url   = page.get("url",   "")
        title = page.get("title", "")
        text  = page.get("text",  "")
        log.info("[%d/%d] Extracting: %s", i, len(pages), url)
        faqs = extract_faqs(url, title, text)
        all_candidates.extend(faqs)
        time.sleep(0.4)  # gentle rate-limit

    log.info("Total candidates: %d", len(all_candidates))

    # Deduplicate and merge
    merged, added, skipped = deduplicate(existing, all_candidates)
    log.info("Added: %d | Skipped (dupes): %d | Total: %d", added, skipped, len(merged))

    # Write faqs.json
    output = {
        "meta": {
            "last_updated":     datetime.now(timezone.utc).isoformat(),
            "pages_processed":  len(pages),
            "scraped_at":       scraped_at,
            "total_faqs":       len(merged),
            "added_this_run":   added,
            "skipped_this_run": skipped,
            "source_site":      "https://brahmaputraboard.gov.in",
            "generator":        f"Cerebras/{MODEL}",
        },
        "faqs": merged,
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    log.info("Written → %s  (%.1f KB)", OUTPUT_FILE,
             os.path.getsize(OUTPUT_FILE) / 1024)
    log.info("═══ Done ═══")

if __name__ == "__main__":
    main()
