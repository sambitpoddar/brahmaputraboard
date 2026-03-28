# Brahmaputra Board – Self-Updating Chatbot

## Why the pipeline is split in two

`brahmaputraboard.gov.in` blocks GitHub Actions' IP ranges at the network level
(TCP timeout on port 443). The fix is simple — split the work:

```
YOUR MACHINE                        GITHUB (free)
─────────────────                   ──────────────────────────────────
1_scrape_local.py   →  push  →      2_extract_faqs.py  (GitHub Actions)
  crawls the site                     reads raw_pages.json
  saves raw_pages.json                sends to Cerebras AI
                                       writes faqs.json
                                       commits back to repo
                                              │
                                              ▼
                                       chatbot widget reads faqs.json
                                       via GitHub raw URL
```

---

## Repository structure

```
bb-chatbot/
├── .github/workflows/
│   └── extract_faqs.yml        ← Auto-triggers when raw_pages.json is pushed
├── data/
│   ├── raw_pages.json          ← YOU push this (from your local machine)
│   └── faqs.json               ← GitHub Actions writes this (auto-committed)
├── scripts/
│   ├── 1_scrape_local.py       ← Run on YOUR machine
│   └── 2_extract_faqs.py       ← Runs on GitHub Actions
├── widget/
│   └── chatbot.html            ← Embed into brahmaputraboard.gov.in
└── README.md
```

---

## One-time setup

### 1. Create the GitHub repository
- Create a **public** GitHub repo (e.g. `sambitpoddar/brahmaputraboard`)
- Push all these files maintaining the folder structure

### 2. Add the Cerebras API key
- Get a free key at [cerebras.ai](https://cerebras.ai)
- Go to repo → **Settings** → **Secrets and variables** → **Actions**
- Click **New repository secret** → Name: `CEREBRAS_API_KEY` → paste key → Save

### 3. Enable GitHub Actions
- Go to the **Actions** tab → enable workflows if prompted

---

## Regular workflow (to update the knowledge base)

### On your machine — whenever you want to update:

```bash
# Install dependencies (first time only)
pip install requests beautifulsoup4

# Run the scraper
python scripts/1_scrape_local.py

# Push the result to GitHub
git add data/raw_pages.json
git commit -m "chore: update scraped pages"
git push
```

That's it. The push automatically triggers GitHub Actions, which:
1. Reads `data/raw_pages.json`
2. Sends each page to Cerebras AI (free) for FAQ extraction
3. Deduplicates against existing FAQs (MD5 + Jaccard similarity)
4. Commits the updated `data/faqs.json` back to the repo

The chatbot widget reads the updated `faqs.json` within seconds.

---

## Embed the widget

Copy three blocks from `widget/chatbot.html` into `brahmaputraboard.gov.in`:

| Block | Where |
|-------|-------|
| `<style>` | Inside `<head>` |
| `<div id="bb-widget">` | Before `</body>` |
| `<script>` | Just before `</body>` |

Update `FAQS_URL` in the script block to your repo's raw URL:
```
https://raw.githubusercontent.com/YOUR_ORG/YOUR_REPO/main/data/faqs.json
```

---

## Cost breakdown

| Service | Free tier | Usage |
|---------|-----------|-------|
| GitHub Actions | 2,000 min/month | ~3–5 min per scrape push |
| Cerebras API | Free | ~pages scraped per run |
| GitHub raw URLs | Free | Unlimited widget reads |
| **Total** | **₹0** | ✅ |

---

## Troubleshooting

**Scraper gets 0 pages**  
→ You're running it on a network that blocks the site. Try a different network or your mobile hotspot.

**GitHub Actions fails at Cerebras step**  
→ Check `CEREBRAS_API_KEY` is set in repo secrets.

**Widget shows "Could not load knowledge base"**  
→ Verify `FAQS_URL` points to the correct raw GitHub URL and the repo is public.

**Bot gives wrong/no answers**  
→ Lower `MATCH_THR` in the widget (e.g. `0.14`) for more permissive matching.
