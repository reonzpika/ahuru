"""
run_monthly.py
Orchestrates the monthly strategic SEO report pipeline:
  1. Fetch GSC data (8 API calls: 28d MoM + 90d YoY)
  2. Analyse into strategic insight buckets
  3. Generate report via Claude API
  4. Save to /reports/monthly/
  5. Email via Resend

Run locally:   python src/run_monthly.py
GitHub Actions: called by .github/workflows/monthly_report.yml
"""

import json
import os
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))

from gsc_fetch_monthly import fetch_monthly_data
from analyse_monthly import analyse_monthly
from report_monthly import generate_monthly_report, save_monthly_report
from email_report import send_report

AUCKLAND = ZoneInfo("Pacific/Auckland")


def _date_first_monday_auckland(year: int, month: int) -> date:
    """Calendar date of the first Monday in year/month (Pacific/Auckland calendar)."""
    first = date(year, month, 1)
    offset = (7 - first.weekday()) % 7
    if first.weekday() == 0:
        return first
    return first + timedelta(days=offset)


def _skip_monthly_schedule_not_first_monday() -> bool:
    """
    For GITHUB_EVENT_NAME=schedule only: skip if today is not the first Monday
    of the month in Pacific/Auckland. Guards against cron DOM/DOW OR semantics.
    """
    if os.environ.get("GITHUB_EVENT_NAME") != "schedule":
        return False
    now = datetime.now(AUCKLAND)
    if now.weekday() != 0:
        return True
    first_mon = _date_first_monday_auckland(now.year, now.month)
    return now.date() != first_mon


def build_monthly_summary(analysis):
    """
    Builds a summary dict compatible with email_report.send_report().
    Maps monthly metrics into the same shape the weekly email template expects.
    """
    mom = analysis["month_on_month"]
    curr = mom["current_28d"]
    prev = mom["previous_28d"]
    changes = mom["changes"]

    return {
        # Use 28d as the "current period" display in the email KPI strip
        "current_7d_clicks": curr["clicks"],
        "current_7d_impressions": curr["impressions"],
        "total_clicks_90d": analysis["year_on_year"]["current_90d"]["clicks"],
        "ranked_pages_90d": analysis["year_on_year"]["current_90d"]["ranked_pages"],
        "clicks_wow_pct": changes["clicks_pct"],        # MoM change shown in email header
        "impressions_wow_pct": changes["impressions_pct"],
        # Extra fields used by monthly email subject line override
        "_report_type": "monthly",
        "_report_month": analysis["report_month"],
    }


def main():
    if _skip_monthly_schedule_not_first_monday():
        print(
            "Skipping monthly pipeline: scheduled run is not the first Monday "
            "of the month (Pacific/Auckland)."
        )
        return

    start = datetime.utcnow()
    print(f"{'='*60}")
    print(f"Āhuru Monthly SEO Report Pipeline")
    print(f"Started: {start.isoformat()}Z")
    print(f"{'='*60}\n")

    # ── Step 1: Fetch ────────────────────────────────────────────────
    print("STEP 1: Fetching GSC data (monthly)")
    print("-" * 40)
    raw_data = fetch_monthly_data()

    # Save raw data
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(data_dir, exist_ok=True)
    date_str = start.strftime("%Y-%m-%d")
    data_path = os.path.join(data_dir, f"gsc_monthly_{date_str}.json")

    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(raw_data, f, indent=2)
    print(f"\nRaw data saved: {data_path}")

    # ── Step 2: Analyse ──────────────────────────────────────────────
    print("\nSTEP 2: Analysing data (monthly)")
    print("-" * 40)
    analysis = analyse_monthly(raw_data)

    mom = analysis["month_on_month"]
    yoy = analysis["year_on_year"]
    print(f"\nSnapshot:")
    print(f"  Current 28d clicks:    {mom['current_28d']['clicks']:,}")
    print(f"  Previous 28d clicks:   {mom['previous_28d']['clicks']:,}")
    mom_pct = mom["changes"]["clicks_pct"]
    if mom_pct is not None:
        direction = "▲" if mom_pct > 0 else "▼"
        print(f"  MoM clicks change:     {direction} {abs(mom_pct)}%")
    print(f"  YoY data available:    {yoy['data_available']}")
    if yoy["data_available"]:
        yoy_pct = yoy["changes"]["clicks_pct"]
        if yoy_pct is not None:
            direction = "▲" if yoy_pct > 0 else "▼"
            print(f"  YoY clicks change:     {direction} {abs(yoy_pct)}%")

    # ── Step 3: Generate report ──────────────────────────────────────
    print("\nSTEP 3: Generating monthly report via Claude API")
    print("-" * 40)
    report_text = generate_monthly_report(analysis)

    # ── Step 4: Save ─────────────────────────────────────────────────
    print("\nSTEP 4: Saving monthly report")
    print("-" * 40)
    report_path = save_monthly_report(report_text)

    # ── Step 5: Email ────────────────────────────────────────────────
    print("\nSTEP 5: Sending email via Resend")
    print("-" * 40)
    resend_key = os.environ.get("RESEND_API_KEY")
    if resend_key:
        try:
            summary = build_monthly_summary(analysis)
            send_report(report_text, summary)
        except Exception as e:
            print(f"Warning: Email failed (report still saved): {e}")
    else:
        print("RESEND_API_KEY not set: skipping email")

    # ── Done ─────────────────────────────────────────────────────────
    elapsed = (datetime.utcnow() - start).total_seconds()
    print(f"\n{'='*60}")
    print(f"Monthly pipeline complete in {elapsed:.1f}s")
    print(f"  Report: {report_path}")
    print(f"  Latest: reports/monthly/latest.md")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
