"""
gsc_fetch_monthly.py
Fetches Google Search Console data for the monthly strategic report.

Reuses get_service() and fetch_search_analytics() from gsc_fetch.py.
Adds three new date ranges not needed by the weekly pipeline:
  - current_28d / previous_28d  — month-on-month comparison
  - last_year_90d               — year-on-year comparison (same window, 52w ago)

The weekly fetch (fetch_all_data) is NOT modified.
"""

import json
import os
from datetime import datetime, timedelta

# Reuse auth + core fetch from the existing module
import sys
sys.path.insert(0, os.path.dirname(__file__))
from gsc_fetch import get_service, fetch_search_analytics, SITE_URL, DATA_LAG_DAYS


def get_monthly_date_ranges():
    """
    Returns date ranges needed for the monthly report.
    All ranges end DATA_LAG_DAYS before today.
    """
    today = datetime.utcnow().date()
    end = today - timedelta(days=DATA_LAG_DAYS)

    # Current 90d — primary window (same as weekly, for YoY base)
    current_90d_end = end
    current_90d_start = end - timedelta(days=90)

    # Same 90d window exactly 52 weeks (364 days) ago — for YoY
    last_year_90d_end = end - timedelta(days=364)
    last_year_90d_start = last_year_90d_end - timedelta(days=90)

    # Current 28d — for MoM
    current_28d_end = end
    current_28d_start = end - timedelta(days=28)

    # Previous 28d — immediately before current 28d
    previous_28d_end = end - timedelta(days=28)
    previous_28d_start = end - timedelta(days=56)

    return {
        "current_90d": {
            "start": current_90d_start.isoformat(),
            "end": current_90d_end.isoformat(),
        },
        "last_year_90d": {
            "start": last_year_90d_start.isoformat(),
            "end": last_year_90d_end.isoformat(),
        },
        "current_28d": {
            "start": current_28d_start.isoformat(),
            "end": current_28d_end.isoformat(),
        },
        "previous_28d": {
            "start": previous_28d_start.isoformat(),
            "end": previous_28d_end.isoformat(),
        },
    }


def fetch_monthly_data():
    """
    Fetches all data needed for the monthly strategic report.

    8 API calls total:
      current_90d:    pages + queries
      last_year_90d:  pages + queries
      current_28d:    pages + queries
      previous_28d:   pages + queries

    No page+query fetch (cannibalisation is a weekly concern, not monthly).
    Estimated runtime: ~60–90 seconds.

    Returns a dict with all raw GSC rows plus metadata.
    """
    service = get_service()
    ranges = get_monthly_date_ranges()

    print(f"Fetching monthly GSC data for {SITE_URL}")
    print(f"Current 90d:    {ranges['current_90d']['start']} → {ranges['current_90d']['end']}")
    print(f"Last year 90d:  {ranges['last_year_90d']['start']} → {ranges['last_year_90d']['end']}")
    print(f"Current 28d:    {ranges['current_28d']['start']} → {ranges['current_28d']['end']}")
    print(f"Previous 28d:   {ranges['previous_28d']['start']} → {ranges['previous_28d']['end']}\n")

    # 1/8 — current 90d pages
    print("1/8 Fetching current 90d page data...")
    current_90d_pages = fetch_search_analytics(
        service,
        ranges["current_90d"]["start"],
        ranges["current_90d"]["end"],
        ["page"],
    )

    # 2/8 — current 90d queries
    print("\n2/8 Fetching current 90d query data...")
    current_90d_queries = fetch_search_analytics(
        service,
        ranges["current_90d"]["start"],
        ranges["current_90d"]["end"],
        ["query"],
    )

    # 3/8 — last year 90d pages (YoY)
    print("\n3/8 Fetching last year 90d page data (YoY)...")
    last_year_90d_pages = fetch_search_analytics(
        service,
        ranges["last_year_90d"]["start"],
        ranges["last_year_90d"]["end"],
        ["page"],
    )

    # 4/8 — last year 90d queries (YoY)
    print("\n4/8 Fetching last year 90d query data (YoY)...")
    last_year_90d_queries = fetch_search_analytics(
        service,
        ranges["last_year_90d"]["start"],
        ranges["last_year_90d"]["end"],
        ["query"],
    )

    # 5/8 — current 28d pages (MoM)
    print("\n5/8 Fetching current 28d page data (MoM)...")
    current_28d_pages = fetch_search_analytics(
        service,
        ranges["current_28d"]["start"],
        ranges["current_28d"]["end"],
        ["page"],
    )

    # 6/8 — current 28d queries (MoM + watchlist + seasonal)
    print("\n6/8 Fetching current 28d query data (MoM + watchlist)...")
    current_28d_queries = fetch_search_analytics(
        service,
        ranges["current_28d"]["start"],
        ranges["current_28d"]["end"],
        ["query"],
    )

    # 7/8 — previous 28d pages (MoM comparison)
    print("\n7/8 Fetching previous 28d page data (MoM comparison)...")
    previous_28d_pages = fetch_search_analytics(
        service,
        ranges["previous_28d"]["start"],
        ranges["previous_28d"]["end"],
        ["page"],
    )

    # 8/8 — previous 28d queries (MoM + watchlist comparison)
    print("\n8/8 Fetching previous 28d query data (MoM + watchlist comparison)...")
    previous_28d_queries = fetch_search_analytics(
        service,
        ranges["previous_28d"]["start"],
        ranges["previous_28d"]["end"],
        ["query"],
    )

    data = {
        "site_url": SITE_URL,
        "fetched_at": datetime.utcnow().isoformat(),
        "date_ranges": ranges,
        "current_90d_pages": current_90d_pages,
        "current_90d_queries": current_90d_queries,
        "last_year_90d_pages": last_year_90d_pages,
        "last_year_90d_queries": last_year_90d_queries,
        "current_28d_pages": current_28d_pages,
        "current_28d_queries": current_28d_queries,
        "previous_28d_pages": previous_28d_pages,
        "previous_28d_queries": previous_28d_queries,
    }

    print(f"\n✓ Monthly fetch complete")
    print(f"  Current 90d pages:     {len(current_90d_pages)}")
    print(f"  Current 90d queries:   {len(current_90d_queries)}")
    print(f"  Last year 90d pages:   {len(last_year_90d_pages)}")
    print(f"  Last year 90d queries: {len(last_year_90d_queries)}")
    print(f"  Current 28d pages:     {len(current_28d_pages)}")
    print(f"  Current 28d queries:   {len(current_28d_queries)}")
    print(f"  Previous 28d pages:    {len(previous_28d_pages)}")
    print(f"  Previous 28d queries:  {len(previous_28d_queries)}")

    return data


# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    data = fetch_monthly_data()

    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(data_dir, exist_ok=True)
    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    out_path = os.path.join(data_dir, f"gsc_monthly_{date_str}.json")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"\nSaved: {out_path}")
