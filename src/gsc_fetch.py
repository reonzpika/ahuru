"""
gsc_fetch.py
Fetches Google Search Console data for ahurucandles.co.nz.

Supports two auth modes:
  1. Local dev:  credentials/service_account.json on disk
  2. GitHub Actions: GOOGLE_SERVICE_ACCOUNT_JSON env var (JSON string)

GSC has a ~3-day data lag — all date ranges account for this.
The API returns max 25,000 rows per call; pagination handles larger datasets.
"""

import json
import os
from datetime import datetime, timedelta

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ── Configuration ────────────────────────────────────────────────────────────

SITE_URL = "sc-domain:ahurucandles.co.nz"
# If your GSC property is a Domain property (sc-domain:), use this instead:
# SITE_URL = "sc-domain:ahurucandles.co.nz"

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
ROW_LIMIT = 25_000   # GSC API maximum per request
DATA_LAG_DAYS = 3    # GSC data is typically 2-3 days behind today

# ── Auth ─────────────────────────────────────────────────────────────────────

def get_service():
    """
    Build the Search Console API service.
    Prefers the GOOGLE_SERVICE_ACCOUNT_JSON env var (GitHub Actions).
    Falls back to credentials/service_account.json for local dev.
    """
    env_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")

    if env_json:
        info = json.loads(env_json)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=SCOPES
        )
    else:
        key_path = os.path.join(
            os.path.dirname(__file__), "..", "credentials", "service_account.json"
        )
        if not os.path.exists(key_path):
            raise FileNotFoundError(
                "No credentials found.\n"
                "Either set GOOGLE_SERVICE_ACCOUNT_JSON env var,\n"
                f"or place your key file at: {key_path}"
            )
        creds = service_account.Credentials.from_service_account_file(
            key_path, scopes=SCOPES
        )

    return build("searchconsole", "v1", credentials=creds)


# ── Core fetch with pagination ────────────────────────────────────────────────

def fetch_search_analytics(service, start_date, end_date, dimensions):
    """
    Fetch all rows for a given date range and dimension set.
    Handles pagination automatically.

    Args:
        service:    Authenticated GSC API service object.
        start_date: ISO date string e.g. "2025-01-01"
        end_date:   ISO date string e.g. "2025-03-14"
        dimensions: List e.g. ["query"], ["page"], ["page", "query"]

    Returns:
        List of row dicts. Each row has:
          keys: list matching dimensions order
          clicks, impressions, ctr, position
    """
    all_rows = []
    start_row = 0

    while True:
        request_body = {
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": dimensions,
            "rowLimit": ROW_LIMIT,
            "startRow": start_row,
        }

        try:
            response = (
                service.searchanalytics()
                .query(siteUrl=SITE_URL, body=request_body)
                .execute()
            )
        except HttpError as e:
            print(f"  GSC API error: {e}")
            raise

        rows = response.get("rows", [])
        all_rows.extend(rows)

        print(f"  Fetched {len(all_rows)} rows so far ({dimensions})...")

        # If we got fewer rows than the limit, we have everything
        if len(rows) < ROW_LIMIT:
            break

        start_row += ROW_LIMIT

    return all_rows


# ── Date range helpers ────────────────────────────────────────────────────────

def get_date_ranges():
    """
    Returns a dict of all date range pairs used in the report.
    All ranges end 3 days before today to account for GSC data lag.
    """
    today = datetime.utcnow().date()
    end = today - timedelta(days=DATA_LAG_DAYS)

    return {
        # 90-day window — primary analysis period
        "90d": {
            "start": (end - timedelta(days=90)).isoformat(),
            "end": end.isoformat(),
        },
        # Current 7-day window
        "current_7d": {
            "start": (end - timedelta(days=7)).isoformat(),
            "end": end.isoformat(),
        },
        # Previous 7-day window (for week-over-week comparison)
        "previous_7d": {
            "start": (end - timedelta(days=14)).isoformat(),
            "end": (end - timedelta(days=8)).isoformat(),
        },
        # 28-day window for monthly view
        "28d": {
            "start": (end - timedelta(days=28)).isoformat(),
            "end": end.isoformat(),
        },
    }


# ── Main fetch ────────────────────────────────────────────────────────────────

def fetch_all_data():
    """
    Fetches all data needed for the weekly report.

    Returns a dict with all raw GSC rows plus metadata.
    """
    service = get_service()
    ranges = get_date_ranges()

    print(f"Fetching GSC data for {SITE_URL}")
    print(f"Primary range: {ranges['90d']['start']} → {ranges['90d']['end']}\n")

    # 1. Queries (90d) — for ranking position analysis
    print("1/6 Fetching 90d query data...")
    queries_90d = fetch_search_analytics(
        service,
        ranges["90d"]["start"],
        ranges["90d"]["end"],
        ["query"],
    )

    # 2. Pages (90d) — for CTR and top page analysis
    print("\n2/6 Fetching 90d page data...")
    pages_90d = fetch_search_analytics(
        service,
        ranges["90d"]["start"],
        ranges["90d"]["end"],
        ["page"],
    )

    # 3. Page + query (90d) — for cannibalisation detection
    print("\n3/6 Fetching 90d page+query data (cannibalisation)...")
    page_query_90d = fetch_search_analytics(
        service,
        ranges["90d"]["start"],
        ranges["90d"]["end"],
        ["page", "query"],
    )

    # 4. Current week (page level) — for week-over-week
    print("\n4/6 Fetching current 7-day page data...")
    current_7d = fetch_search_analytics(
        service,
        ranges["current_7d"]["start"],
        ranges["current_7d"]["end"],
        ["page"],
    )

    # 5. Previous week (page level) — for week-over-week comparison
    print("\n5/6 Fetching previous 7-day page data...")
    previous_7d = fetch_search_analytics(
        service,
        ranges["previous_7d"]["start"],
        ranges["previous_7d"]["end"],
        ["page"],
    )

    # 6. 28d queries — for recent trend context
    print("\n6/6 Fetching 28d query data...")
    queries_28d = fetch_search_analytics(
        service,
        ranges["28d"]["start"],
        ranges["28d"]["end"],
        ["query"],
    )

    data = {
        "site_url": SITE_URL,
        "fetched_at": datetime.utcnow().isoformat(),
        "date_ranges": ranges,
        "queries_90d": queries_90d,
        "pages_90d": pages_90d,
        "page_query_90d": page_query_90d,
        "current_7d": current_7d,
        "previous_7d": previous_7d,
        "queries_28d": queries_28d,
    }

    print(f"\n✓ Fetch complete")
    print(f"  Queries (90d):     {len(queries_90d)}")
    print(f"  Pages (90d):       {len(pages_90d)}")
    print(f"  Page+query (90d):  {len(page_query_90d)}")
    print(f"  Current 7d pages:  {len(current_7d)}")
    print(f"  Previous 7d pages: {len(previous_7d)}")

    return data


# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import os

    data = fetch_all_data()

    os.makedirs(os.path.join(os.path.dirname(__file__), "..", "data"), exist_ok=True)
    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    out_path = os.path.join(os.path.dirname(__file__), "..", "data", f"gsc_{date_str}.json")

    with open(out_path, "w") as f:
        json.dump(data, f, indent=2)

    print(f"\nSaved: {out_path}")
