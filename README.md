# Āhuru SEO Automation

Automated SEO monitoring and reporting for [ahurucandles.co.nz](https://ahurucandles.co.nz).

**Two components:**
1. **Interactive analysis** — `mcp-gsc` + Claude Desktop/Cursor for ad-hoc queries
2. **Automated weekly report** — GitHub Actions runs every Sunday, commits a Markdown report

---

## Part 1: Interactive Analysis (mcp-gsc + Claude)

This lets you ask Claude natural-language questions against live GSC data.

### 1.1 Google Cloud Setup

You need a service account that has read access to Ahuru's GSC property.

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (e.g. `ahuru-seo`)
3. Enable the **Google Search Console API**:
   - APIs & Services → Library → search "Search Console API" → Enable
4. Create a service account:
   - APIs & Services → Credentials → Create Credentials → Service Account
   - Name: `ahuru-gsc-reader`
   - Role: skip (leave blank) — GSC manages access separately
   - Create and continue → Done
5. Generate a JSON key:
   - Click the service account → Keys tab → Add Key → Create new key → JSON
   - Download the JSON file — this is your `service_account.json`
6. Add the service account to GSC:
   - Open [Google Search Console](https://search.google.com/search-console)
   - Select the Ahuru property → Settings → Users and permissions → Add user
   - Paste the service account email (looks like `ahuru-gsc-reader@ahuru-seo.iam.gserviceaccount.com`)
   - Permission: **Full** (needed to fetch all data)

### 1.2 mcp-gsc Setup

```bash
git clone https://github.com/AminForou/mcp-gsc.git
cd mcp-gsc
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Place your `service_account.json` somewhere secure (e.g. `~/credentials/ahuru_gsc.json`).

### 1.3 Connect to Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (Mac):

```json
{
  "mcpServers": {
    "gsc": {
      "command": "/FULL/PATH/TO/mcp-gsc/.venv/bin/python",
      "args": ["/FULL/PATH/TO/mcp-gsc/gsc_server.py"],
      "env": {
        "GSC_CREDENTIALS_PATH": "/FULL/PATH/TO/ahuru_gsc.json",
        "GSC_SKIP_OAUTH": "true"
      }
    }
  }
}
```

Replace all `/FULL/PATH/TO/` with actual absolute paths.

Restart Claude Desktop. You should see a GSC tool icon in the interface.

### 1.4 Connect to Cursor

Cursor → Settings → Cursor Settings → Tools and integrations → New MCP server.

Add:
```json
{
  "gsc": {
    "command": "/FULL/PATH/TO/mcp-gsc/.venv/bin/python",
    "args": ["/FULL/PATH/TO/mcp-gsc/gsc_server.py"],
    "env": {
      "GSC_CREDENTIALS_PATH": "/FULL/PATH/TO/ahuru_gsc.json",
      "GSC_SKIP_OAUTH": "true"
    }
  }
}
```

### 1.5 First Queries to Run

Once connected, open Claude Desktop and ask:

```
What are the top 20 queries for ahurucandles.co.nz by impressions in the last 90 days?
```

```
Which pages on ahurucandles.co.nz have more than 100 impressions but less than 3% CTR?
Suggest improved meta titles for each.
```

```
Are there any keyword cannibalisation issues on ahurucandles.co.nz?
Cross-reference pages competing for the same queries and recommend which page should own each query.
```

```
Which queries for ahurucandles.co.nz are ranking in positions 5–15 with more than 30 impressions?
These are quick wins — what content changes would push them to page 1?
```

```
Check the indexing status of these pages:
- https://www.ahurucandles.co.nz/collections/fidget-rings-nz
- https://www.ahurucandles.co.nz/blogs/fidget-ring
- https://www.ahurucandles.co.nz/collections/anxiety-rings-nz
Are there any crawl or indexing issues?
```

---

## Part 2: Automated Weekly Report (GitHub Actions)

Runs every Sunday. Fetches GSC data, analyses it, generates a Markdown report via Claude API, and commits it to `reports/`.

### 2.1 Repository Secrets

Go to: GitHub repo → Settings → Secrets and variables → Actions → New repository secret

Add two secrets:

**`GOOGLE_SERVICE_ACCOUNT_JSON`**
The full contents of your `service_account.json` file (the entire JSON as a string).

**`ANTHROPIC_API_KEY`**
Your Anthropic API key from [console.anthropic.com](https://console.anthropic.com).

**Shopify baseline SEO (optional but recommended)**  
The same three secrets as the Apply SEO Changes workflow (`SHOPIFY_CLIENT_ID`, `SHOPIFY_CLIENT_SECRET`, `SHOPIFY_DOMAIN`) let the weekly run populate `previous_seo_*` on new `meta_update` tasks. If they are omitted, task generation still works; baseline fields stay empty until you run apply or [`src/backfill_previous_seo.py`](src/backfill_previous_seo.py). Set `SEO_SKIP_BASELINE_FETCH=1` to disable baseline fetches even when credentials exist.

### 2.2 Verify Your GSC Property URL

Open `src/gsc_fetch.py` and confirm `SITE_URL` matches your GSC property exactly.

Check in GSC: the property URL is shown in the top-left dropdown. It will be either:
- `https://www.ahurucandles.co.nz/` (URL prefix property)
- `sc-domain:ahurucandles.co.nz` (Domain property)

Update `SITE_URL` in `gsc_fetch.py` to match.

### 2.3 Local Test Run

Before relying on GitHub Actions, test locally:

```bash
# Clone this repo
git clone https://github.com/YOUR_USERNAME/ahuru-seo.git
cd ahuru-seo

# Install dependencies
pip install -r requirements.txt

# Place your service account key
mkdir credentials
cp ~/path/to/your/service_account.json credentials/service_account.json

# Set your Anthropic API key
export ANTHROPIC_API_KEY=sk-ant-...

# Run the full pipeline
python src/run_weekly.py
```

The report will appear at `reports/YYYY-MM-DD.md` and `reports/latest.md`.

### 2.4 First GitHub Actions Run

After pushing to GitHub and setting the secrets:

1. Go to: GitHub repo → Actions tab → Weekly SEO Report
2. Click **Run workflow** → Run workflow (manual trigger)
3. Watch the run — it should complete in ~60 seconds
4. Check `reports/latest.md` in the repo for output

If it fails, check the Actions log. Common issues:
- Wrong `SITE_URL` in `gsc_fetch.py` — must match GSC property exactly
- Service account not added to GSC property as a user
- `ANTHROPIC_API_KEY` secret not set

### 2.5 Schedule

The workflow runs **every Sunday at 8am UTC** (8–9pm NZ time).

To change the schedule, edit `.github/workflows/weekly_report.yml` and update the cron expression. [crontab.guru](https://crontab.guru) is useful for this.

---

## Project Structure

```
ahuru-seo/
├── .github/
│   └── workflows/
│       └── weekly_report.yml   ← GitHub Actions cron job
├── src/
│   ├── gsc_fetch.py            ← Pulls GSC data via API
│   ├── analyse.py              ← Processes data into insight buckets
│   ├── report.py               ← Calls Claude API, generates report
│   └── run_weekly.py           ← Orchestrates all three steps
├── prompts/
│   └── system_prompt.md        ← Ahuru brand context for Claude
├── reports/
│   ├── README.md
│   ├── latest.md               ← Most recent report (auto-updated)
│   └── YYYY-MM-DD.md           ← Dated archive
├── credentials/                ← Gitignored — local dev only
├── data/                       ← Gitignored — raw GSC JSON
├── requirements.txt
├── .gitignore
└── README.md
```

---

## Extending the Pipeline

### Add Shopify data

Install and configure [`GeLi2001/shopify-mcp`](https://github.com/GeLi2001/shopify-mcp) alongside mcp-gsc in your Claude config:

```json
{
  "mcpServers": {
    "gsc": { ... },
    "shopify": {
      "command": "npx",
      "args": [
        "shopify-mcp",
        "--accessToken", "YOUR_SHOPIFY_ACCESS_TOKEN",
        "--domain",      "ahurucandles.myshopify.com"
      ]
    }
  }
}
```

Then ask Claude: *"Which fidget ring pages are getting impressions in GSC but have zero corresponding sales in Shopify this month?"*

### Add GA4 data

The same service account works for GA4. Enable the Google Analytics Data API in your Cloud project, add the service account as a Viewer in GA4, then fetch session/conversion data alongside GSC data.

### Cost

At current Claude API pricing, each weekly report costs approximately $0.05–0.15 NZD depending on data volume. Negligible.
