"""
analyse.py
Processes raw GSC data into structured insight buckets.

This runs BEFORE the Claude API call, so we send Claude a compact
structured summary rather than thousands of raw rows.
Keeps Claude API costs low and improves analysis quality.
"""

from collections import defaultdict


# ── Thresholds (tune these as the site grows) ─────────────────────────────────

MIN_IMPRESSIONS_CTR_AUDIT = 50     # Min 90d impressions to flag as CTR opportunity
CTR_OPPORTUNITY_THRESHOLD = 0.03   # < 3% CTR is flagged
MAX_POSITION_CTR_AUDIT = 20        # Only audit pages ranking within top 20

MIN_IMPRESSIONS_QUICK_WIN = 20     # Min 90d impressions for a quick-win query
QUICK_WIN_POSITION_MIN = 5         # Position band start
QUICK_WIN_POSITION_MAX = 15        # Position band end (just off page 1)

WOW_CHANGE_THRESHOLD = 0.20        # 20% week-over-week change to surface
MIN_IMPRESSIONS_WOW = 10           # Min impressions in previous period to compare

MIN_IMPRESSIONS_CANNIBALISATION = 10   # Per page, per query, to count
MIN_TOTAL_CANNIBALISATION = 30         # Total query impressions to surface issue


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_keys(row, indices):
    """Extract key values from a GSC row by dimension index."""
    return tuple(row["keys"][i] for i in indices)


def _safe_ctr_pct(ctr):
    """Format CTR as rounded percentage string."""
    return round(ctr * 100, 2)


# ── Analysis functions ────────────────────────────────────────────────────────

def ctr_opportunities(pages_90d):
    """
    Pages with high impressions but low CTR.
    These are meta title / description fixes — easiest ranking wins.
    """
    results = []
    for row in pages_90d:
        page = row["keys"][0]
        impressions = row["impressions"]
        clicks = row["clicks"]
        ctr = row["ctr"]
        position = row["position"]

        if (
            impressions >= MIN_IMPRESSIONS_CTR_AUDIT
            and ctr < CTR_OPPORTUNITY_THRESHOLD
            and position <= MAX_POSITION_CTR_AUDIT
        ):
            results.append(
                {
                    "page": page,
                    "impressions": impressions,
                    "clicks": clicks,
                    "ctr_pct": _safe_ctr_pct(ctr),
                    "avg_position": round(position, 1),
                }
            )

    # Sort by impressions descending — biggest missed-click opportunity first
    results.sort(key=lambda x: x["impressions"], reverse=True)
    return results[:20]


def quick_wins(queries_90d):
    """
    Queries ranking in positions 5–15 with decent impressions.
    A targeted content update or title change can push these to page 1.
    """
    results = []
    for row in queries_90d:
        query = row["keys"][0]
        position = row["position"]
        impressions = row["impressions"]

        if (
            QUICK_WIN_POSITION_MIN <= position <= QUICK_WIN_POSITION_MAX
            and impressions >= MIN_IMPRESSIONS_QUICK_WIN
        ):
            results.append(
                {
                    "query": query,
                    "avg_position": round(position, 1),
                    "impressions": impressions,
                    "clicks": row["clicks"],
                    "ctr_pct": _safe_ctr_pct(row["ctr"]),
                }
            )

    results.sort(key=lambda x: x["impressions"], reverse=True)
    return results[:20]


def week_over_week(current_7d, previous_7d):
    """
    Compares current 7-day period against previous 7-day period per page.
    Surfaces pages with > 20% impression change in either direction.
    """
    def aggregate(rows):
        pages = defaultdict(lambda: {"impressions": 0, "clicks": 0})
        for row in rows:
            page = row["keys"][0]
            pages[page]["impressions"] += row["impressions"]
            pages[page]["clicks"] += row["clicks"]
        return pages

    current = aggregate(current_7d)
    previous = aggregate(previous_7d)

    changes = []
    all_pages = set(list(current.keys()) + list(previous.keys()))

    for page in all_pages:
        curr_impr = current[page]["impressions"]
        prev_impr = previous[page]["impressions"]

        # Skip if previous period had too few impressions to be meaningful
        if prev_impr < MIN_IMPRESSIONS_WOW:
            continue

        pct_change = (curr_impr - prev_impr) / prev_impr

        if abs(pct_change) >= WOW_CHANGE_THRESHOLD:
            changes.append(
                {
                    "page": page,
                    "current_impressions": curr_impr,
                    "previous_impressions": prev_impr,
                    "change_pct": round(pct_change * 100, 1),
                    "direction": "up" if pct_change > 0 else "down",
                }
            )

    # Sort by absolute change size
    changes.sort(key=lambda x: abs(x["change_pct"]), reverse=True)
    return changes[:15]


def cannibalisation(page_query_90d):
    """
    Finds queries where multiple pages are competing for the same ranking.
    This dilutes ranking signal — one page should own each query.

    Common Ahuru example: multiple fidget ring blog posts + collection page
    all ranking for "fidget rings NZ".
    """
    # Group by query: which pages rank for each?
    query_pages = defaultdict(list)

    for row in page_query_90d:
        page = row["keys"][0]
        query = row["keys"][1]
        impressions = row["impressions"]
        position = row["position"]

        if impressions >= MIN_IMPRESSIONS_CANNIBALISATION:
            query_pages[query].append(
                {
                    "page": page,
                    "impressions": impressions,
                    "avg_position": round(position, 1),
                    "clicks": row["clicks"],
                }
            )

    # Keep only queries with 2+ competing pages
    results = []
    for query, pages in query_pages.items():
        if len(pages) < 2:
            continue

        total_impressions = sum(p["impressions"] for p in pages)
        if total_impressions < MIN_TOTAL_CANNIBALISATION:
            continue

        # Sort pages by impressions (dominant page first)
        pages_sorted = sorted(pages, key=lambda x: x["impressions"], reverse=True)

        results.append(
            {
                "query": query,
                "total_impressions": total_impressions,
                "competing_pages": pages_sorted,
                "page_count": len(pages),
            }
        )

    results.sort(key=lambda x: x["total_impressions"], reverse=True)
    return results[:10]


def top_pages(pages_90d, n=10):
    """Top N pages by clicks over 90 days."""
    sorted_pages = sorted(pages_90d, key=lambda x: x["clicks"], reverse=True)
    return [
        {
            "page": r["keys"][0],
            "clicks": r["clicks"],
            "impressions": r["impressions"],
            "ctr_pct": _safe_ctr_pct(r["ctr"]),
            "avg_position": round(r["position"], 1),
        }
        for r in sorted_pages[:n]
    ]


def top_queries(queries_90d, n=20):
    """Top N queries by clicks over 90 days."""
    sorted_queries = sorted(queries_90d, key=lambda x: x["clicks"], reverse=True)
    return [
        {
            "query": r["keys"][0],
            "clicks": r["clicks"],
            "impressions": r["impressions"],
            "ctr_pct": _safe_ctr_pct(r["ctr"]),
            "avg_position": round(r["position"], 1),
        }
        for r in sorted_queries[:n]
    ]


def site_summary(pages_90d, current_7d, previous_7d):
    """High-level numbers for the report header."""
    total_clicks_90d = sum(r["clicks"] for r in pages_90d)
    total_impressions_90d = sum(r["impressions"] for r in pages_90d)
    ranked_pages = len(pages_90d)

    curr_clicks = sum(r["clicks"] for r in current_7d)
    curr_impressions = sum(r["impressions"] for r in current_7d)
    prev_clicks = sum(r["clicks"] for r in previous_7d)
    prev_impressions = sum(r["impressions"] for r in previous_7d)

    def pct_change(curr, prev):
        if prev == 0:
            return None
        return round(((curr - prev) / prev) * 100, 1)

    return {
        "ranked_pages_90d": ranked_pages,
        "total_clicks_90d": total_clicks_90d,
        "total_impressions_90d": total_impressions_90d,
        "current_7d_clicks": curr_clicks,
        "current_7d_impressions": curr_impressions,
        "previous_7d_clicks": prev_clicks,
        "previous_7d_impressions": prev_impressions,
        "clicks_wow_pct": pct_change(curr_clicks, prev_clicks),
        "impressions_wow_pct": pct_change(curr_impressions, prev_impressions),
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def analyse(data):
    """
    Run all analysis on raw GSC data.
    Returns a structured dict ready to send to the Claude API.
    """
    print("Running analysis...")

    result = {
        "summary": site_summary(
            data["pages_90d"],
            data["current_7d"],
            data["previous_7d"],
        ),
        "ctr_opportunities": ctr_opportunities(data["pages_90d"]),
        "quick_wins": quick_wins(data["queries_90d"]),
        "week_over_week": week_over_week(data["current_7d"], data["previous_7d"]),
        "cannibalisation": cannibalisation(data["page_query_90d"]),
        "top_pages_90d": top_pages(data["pages_90d"], n=10),
        "top_queries_90d": top_queries(data["queries_90d"], n=20),
        "date_ranges": data["date_ranges"],
    }

    print(f"  CTR opportunities:   {len(result['ctr_opportunities'])}")
    print(f"  Quick wins:          {len(result['quick_wins'])}")
    print(f"  WoW changes:         {len(result['week_over_week'])}")
    print(f"  Cannibalisation:     {len(result['cannibalisation'])}")

    return result


if __name__ == "__main__":
    import json
    import glob
    import os

    data_files = sorted(glob.glob(os.path.join(os.path.dirname(__file__), "..", "data", "gsc_*.json")))
    if not data_files:
        raise FileNotFoundError("No data files found. Run gsc_fetch.py first.")

    with open(data_files[-1]) as f:
        data = json.load(f)

    result = analyse(data)
    print(json.dumps(result["summary"], indent=2))
