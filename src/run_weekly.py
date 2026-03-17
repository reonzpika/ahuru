"""
run_weekly.py
Orchestrates the full weekly SEO report pipeline:
  1. Fetch GSC data
  2. Analyse into insight buckets
  3. Generate report via Claude API
  4. Save to /reports/
  5. Email report via Resend

Run locally:   python src/run_weekly.py
GitHub Actions: called by .github/workflows/weekly_report.yml
"""

import json
import os
import sys
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

# Add src/ to path so imports work when called from repo root
sys.path.insert(0, os.path.dirname(__file__))

from gsc_fetch import fetch_all_data
from analyse import analyse
from report import generate_report, save_report
from email_report import send_report


def main():
    start = datetime.utcnow()
    print(f"{'='*60}")
    print(f"Āhuru Weekly SEO Report Pipeline")
    print(f"Started: {start.isoformat()}Z")
    print(f"{'='*60}\n")

    # ── Step 1: Fetch ────────────────────────────────────────────────
    print("STEP 1: Fetching GSC data")
    print("-" * 40)
    raw_data = fetch_all_data()

    # Save raw data for debugging and historical reference
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(data_dir, exist_ok=True)
    date_str = start.strftime("%Y-%m-%d")
    data_path = os.path.join(data_dir, f"gsc_{date_str}.json")

    with open(data_path, "w") as f:
        json.dump(raw_data, f, indent=2)
    print(f"\nRaw data saved: {data_path}")

    # ── Step 2: Analyse ──────────────────────────────────────────────
    print("\nSTEP 2: Analysing data")
    print("-" * 40)
    analysis = analyse(raw_data)

    summary = analysis["summary"]
    print(f"\nSummary:")
    print(f"  Ranked pages (90d):      {summary['ranked_pages_90d']}")
    print(f"  Total clicks (90d):      {summary['total_clicks_90d']:,}")
    print(f"  Total impressions (90d): {summary['total_impressions_90d']:,}")
    print(f"  This week clicks:        {summary['current_7d_clicks']:,}")
    print(f"  Last week clicks:        {summary['previous_7d_clicks']:,}")
    if summary["clicks_wow_pct"] is not None:
        direction = "▲" if summary["clicks_wow_pct"] > 0 else "▼"
        print(f"  WoW clicks change:       {direction} {abs(summary['clicks_wow_pct'])}%")

    # ── Step 3: Generate report ──────────────────────────────────────
    print("\nSTEP 3: Generating report via Claude API")
    print("-" * 40)
    report_text = generate_report(analysis)

    # ── Step 4: Save ─────────────────────────────────────────────────
    print("\nSTEP 4: Saving report")
    print("-" * 40)
    report_path = save_report(report_text)

    # ── Step 5: Email ────────────────────────────────────────────────
    print("\nSTEP 5: Sending email via Resend")
    print("-" * 40)
    resend_key = os.environ.get("RESEND_API_KEY")
    if resend_key:
        try:
            send_report(report_text, summary)
        except Exception as e:
            # Email failure does not fail the whole pipeline
            print(f"Warning: Email failed (report still saved): {e}")
    else:
        print("RESEND_API_KEY not set — skipping email")

    # ── Done ─────────────────────────────────────────────────────────
    elapsed = (datetime.utcnow() - start).total_seconds()
    print(f"\n{'='*60}")
    print(f"Pipeline complete in {elapsed:.1f}s")
    print(f"  Report: {report_path}")
    print(f"  Latest: reports/latest.md")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
