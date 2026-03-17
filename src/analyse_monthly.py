"""
analyse_monthly.py
Monthly-specific analysis functions.

These are SEPARATE from analyse.py — the weekly pipeline is untouched.
Called only by run_monthly.py.

Four new analysis buckets:
  1. month_on_month       — current 28d vs previous 28d
  2. year_on_year         — current 90d vs same window 52 weeks ago
  3. fidget_ring_watchlist — fixed query list, position + impression tracking
  4. seasonal_flag        — candle readiness check (active Aug–Dec only)
"""

from collections import defaultdict
from datetime import datetime


# ── Fidget ring / anxiety jewellery watchlist ─────────────────────────────────
# Edit this list as the business evolves.
# These are the queries that directly drive revenue — tracked every month.

WATCHLIST_QUERIES = [
    "fidget ring",
    "fidget rings",
    "fidget rings nz",
    "fidget ring nz",
    "anxiety ring",
    "anxiety rings",
    "anxiety rings nz",
    "anxiety ring nz",
    "spinner ring",
    "spinner rings",
    "spinner rings nz",
    "fidget ring for adhd",
    "fidget ring adhd nz",
    "sterling silver fidget ring",
    "fidget ring sterling silver nz",
]

# Candle queries to surface in seasonal flag (Aug–Dec only)
CANDLE_QUERIES = [
    "soy candles nz",
    "nz soy candles",
    "scented candles nz",
    "woodwick candles nz",
    "essential oil candles nz",
    "candles nz",
    "soy wax candles nz",
    "christmas candles nz",
    "gift candles nz",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_ctr_pct(ctr):
    return round(ctr * 100, 2)


def _pct_change(curr, prev):
    if prev == 0:
        return None
    return round(((curr - prev) / prev) * 100, 1)


def _aggregate_pages(rows):
    """Sum clicks + impressions per page across a set of rows."""
    pages = defaultdict(lambda: {"clicks": 0, "impressions": 0, "position_sum": 0.0, "position_count": 0})
    for row in rows:
        page = row["keys"][0]
        pages[page]["clicks"] += row["clicks"]
        pages[page]["impressions"] += row["impressions"]
        pages[page]["position_sum"] += row["position"] * row["impressions"]
        pages[page]["position_count"] += row["impressions"]
    return pages


def _aggregate_queries(rows):
    """Sum clicks + impressions per query across a set of rows."""
    queries = defaultdict(lambda: {"clicks": 0, "impressions": 0, "position_sum": 0.0, "position_count": 0})
    for row in rows:
        query = row["keys"][0]
        queries[query]["clicks"] += row["clicks"]
        queries[query]["impressions"] += row["impressions"]
        queries[query]["position_sum"] += row["position"] * row["impressions"]
        queries[query]["position_count"] += row["impressions"]
    return queries


def _weighted_position(d):
    """Impression-weighted average position."""
    if d["position_count"] == 0:
        return None
    return round(d["position_sum"] / d["position_count"], 1)


# ── 1. Month-on-month ─────────────────────────────────────────────────────────

def month_on_month(current_28d_pages, previous_28d_pages,
                   current_28d_queries, previous_28d_queries):
    """
    Compares current 28-day period against the prior 28-day period.
    Returns site-level totals and per-metric percentage changes.
    """
    def totals(rows):
        clicks = sum(r["clicks"] for r in rows)
        impressions = sum(r["impressions"] for r in rows)
        ctr = clicks / impressions if impressions else 0
        # Impression-weighted avg position
        pos_sum = sum(r["position"] * r["impressions"] for r in rows)
        pos = pos_sum / impressions if impressions else 0
        return {
            "clicks": clicks,
            "impressions": impressions,
            "ctr_pct": _safe_ctr_pct(ctr),
            "avg_position": round(pos, 1),
        }

    curr = totals(current_28d_pages)
    prev = totals(previous_28d_pages)

    # Top pages this period (by clicks)
    curr_pages = _aggregate_pages(current_28d_pages)
    top_pages = sorted(
        [
            {
                "page": page,
                "clicks": d["clicks"],
                "impressions": d["impressions"],
                "avg_position": _weighted_position(d),
            }
            for page, d in curr_pages.items()
        ],
        key=lambda x: x["clicks"],
        reverse=True,
    )[:10]

    # Top queries this period (by clicks)
    curr_queries = _aggregate_queries(current_28d_queries)
    top_queries = sorted(
        [
            {
                "query": q,
                "clicks": d["clicks"],
                "impressions": d["impressions"],
                "avg_position": _weighted_position(d),
            }
            for q, d in curr_queries.items()
        ],
        key=lambda x: x["clicks"],
        reverse=True,
    )[:20]

    return {
        "current_28d": curr,
        "previous_28d": prev,
        "changes": {
            "clicks_pct": _pct_change(curr["clicks"], prev["clicks"]),
            "impressions_pct": _pct_change(curr["impressions"], prev["impressions"]),
            "ctr_pct_delta": round(curr["ctr_pct"] - prev["ctr_pct"], 2),
            "position_delta": round(curr["avg_position"] - prev["avg_position"], 1),
        },
        "top_pages_28d": top_pages,
        "top_queries_28d": top_queries,
    }


# ── 2. Year-on-year ───────────────────────────────────────────────────────────

def year_on_year(current_90d_pages, last_year_90d_pages,
                 current_90d_queries, last_year_90d_queries):
    """
    Compares current 90-day window against the same 90-day window 52 weeks ago.

    NOTE: GSC retains 16 months of data. If the site was added to GSC less than
    ~13 months ago, last_year data will be sparse or empty. Claude is instructed
    to note this gracefully in the report.
    """
    def totals(rows):
        clicks = sum(r["clicks"] for r in rows)
        impressions = sum(r["impressions"] for r in rows)
        ctr = clicks / impressions if impressions else 0
        pos_sum = sum(r["position"] * r["impressions"] for r in rows)
        pos = pos_sum / impressions if impressions else 0
        ranked_pages = len(set(r["keys"][0] for r in rows))
        return {
            "clicks": clicks,
            "impressions": impressions,
            "ctr_pct": _safe_ctr_pct(ctr),
            "avg_position": round(pos, 1),
            "ranked_pages": ranked_pages,
        }

    curr = totals(current_90d_pages)
    prev = totals(last_year_90d_pages)
    data_available = len(last_year_90d_pages) > 0

    # Top queries this year vs last year
    curr_q = _aggregate_queries(current_90d_queries)
    prev_q = _aggregate_queries(last_year_90d_queries)

    # Find queries present in both periods — show movement
    shared_queries = set(curr_q.keys()) & set(prev_q.keys())
    query_comparison = []
    for q in shared_queries:
        c = curr_q[q]
        p = prev_q[q]
        query_comparison.append({
            "query": q,
            "current_clicks": c["clicks"],
            "previous_clicks": p["clicks"],
            "clicks_change_pct": _pct_change(c["clicks"], p["clicks"]),
            "current_position": _weighted_position(c),
            "previous_position": _weighted_position(p),
        })
    # Sort by current clicks desc, cap at 20
    query_comparison.sort(key=lambda x: x["current_clicks"], reverse=True)
    query_comparison = query_comparison[:20]

    # New queries this year (not present last year)
    new_queries = sorted(
        [
            {
                "query": q,
                "clicks": curr_q[q]["clicks"],
                "impressions": curr_q[q]["impressions"],
                "avg_position": _weighted_position(curr_q[q]),
            }
            for q in curr_q if q not in prev_q and curr_q[q]["clicks"] >= 5
        ],
        key=lambda x: x["clicks"],
        reverse=True,
    )[:10]

    # Lost queries (present last year, gone this year)
    lost_queries = sorted(
        [
            {
                "query": q,
                "previous_clicks": prev_q[q]["clicks"],
                "previous_impressions": prev_q[q]["impressions"],
            }
            for q in prev_q if q not in curr_q and prev_q[q]["clicks"] >= 5
        ],
        key=lambda x: x["previous_clicks"],
        reverse=True,
    )[:10]

    return {
        "data_available": data_available,
        "current_90d": curr,
        "last_year_90d": prev,
        "changes": {
            "clicks_pct": _pct_change(curr["clicks"], prev["clicks"]) if data_available else None,
            "impressions_pct": _pct_change(curr["impressions"], prev["impressions"]) if data_available else None,
            "ctr_pct_delta": round(curr["ctr_pct"] - prev["ctr_pct"], 2) if data_available else None,
            "position_delta": round(curr["avg_position"] - prev["avg_position"], 1) if data_available else None,
            "ranked_pages_delta": curr["ranked_pages"] - prev["ranked_pages"] if data_available else None,
        },
        "query_comparison": query_comparison,
        "new_queries_this_year": new_queries,
        "lost_queries_vs_last_year": lost_queries,
    }


# ── 3. Fidget ring watchlist ──────────────────────────────────────────────────

def fidget_ring_watchlist(current_28d_queries, previous_28d_queries):
    """
    Tracks a fixed set of high-value fidget ring / anxiety jewellery queries.
    Returns current position, impressions, clicks, and month-on-month movement.

    These queries directly drive revenue — tracked regardless of season.
    """
    curr_q = _aggregate_queries(current_28d_queries)
    prev_q = _aggregate_queries(previous_28d_queries)

    results = []
    for query in WATCHLIST_QUERIES:
        q_lower = query.lower()
        curr = curr_q.get(q_lower)
        prev = prev_q.get(q_lower)

        if curr is None and prev is None:
            # Query not in GSC at all — still include so it's visible
            results.append({
                "query": query,
                "status": "not_ranking",
                "current_impressions": 0,
                "current_clicks": 0,
                "current_position": None,
                "previous_position": None,
                "position_change": None,
                "impressions_change_pct": None,
            })
            continue

        curr_pos = _weighted_position(curr) if curr else None
        prev_pos = _weighted_position(prev) if prev else None
        pos_change = None
        if curr_pos is not None and prev_pos is not None:
            pos_change = round(curr_pos - prev_pos, 1)  # negative = improved

        results.append({
            "query": query,
            "status": "ranking" if curr else "dropped",
            "current_impressions": curr["impressions"] if curr else 0,
            "current_clicks": curr["clicks"] if curr else 0,
            "current_position": curr_pos,
            "previous_position": prev_pos,
            "position_change": pos_change,
            "impressions_change_pct": _pct_change(
                curr["impressions"] if curr else 0,
                prev["impressions"] if prev else 0,
            ),
        })

    # Sort: ranking first, then by impressions desc
    results.sort(key=lambda x: (x["status"] != "ranking", -(x["current_impressions"])))
    return results


# ── 4. Seasonal flag ──────────────────────────────────────────────────────────

def seasonal_flag(current_28d_queries, run_month=None):
    """
    Checks candle keyword performance and content readiness.
    Only meaningful August–December (NZ pre-Christmas gifting season).

    Outside that window, returns a minimal dict with active=False so Claude
    can skip the section entirely.

    Args:
        current_28d_queries: List of query rows from current 28d fetch
        run_month: int 1–12. Defaults to current UTC month.
    """
    if run_month is None:
        run_month = datetime.utcnow().month

    # Active only Aug–Dec (months 8–12)
    is_active = run_month >= 8

    if not is_active:
        return {
            "active": False,
            "run_month": run_month,
            "message": f"Seasonal flag inactive — current month is {run_month}. Activates in August.",
        }

    curr_q = _aggregate_queries(current_28d_queries)

    candle_data = []
    for query in CANDLE_QUERIES:
        q_lower = query.lower()
        d = curr_q.get(q_lower)
        if d:
            candle_data.append({
                "query": query,
                "impressions": d["impressions"],
                "clicks": d["clicks"],
                "avg_position": _weighted_position(d),
            })
        else:
            candle_data.append({
                "query": query,
                "impressions": 0,
                "clicks": 0,
                "avg_position": None,
            })

    # Sort by impressions desc
    candle_data.sort(key=lambda x: x["impressions"], reverse=True)

    total_candle_impressions = sum(d["impressions"] for d in candle_data)
    total_candle_clicks = sum(d["clicks"] for d in candle_data)

    # Weeks until peak (assume Dec 1 is peak)
    now = datetime.utcnow()
    peak = datetime(now.year, 12, 1)
    if now > peak:
        peak = datetime(now.year + 1, 12, 1)
    weeks_to_peak = max(0, (peak - now).days // 7)

    return {
        "active": True,
        "run_month": run_month,
        "weeks_to_peak": weeks_to_peak,
        "total_candle_impressions_28d": total_candle_impressions,
        "total_candle_clicks_28d": total_candle_clicks,
        "candle_queries": candle_data,
    }


# ── Main entry point ──────────────────────────────────────────────────────────

def analyse_monthly(data):
    """
    Run all monthly analysis on raw GSC data.
    Returns a structured dict ready to send to the Claude API.

    Expected keys in data:
      current_28d_pages, previous_28d_pages
      current_28d_queries, previous_28d_queries
      current_90d_pages, last_year_90d_pages
      current_90d_queries, last_year_90d_queries
    """
    print("Running monthly analysis...")

    mom = month_on_month(
        data["current_28d_pages"],
        data["previous_28d_pages"],
        data["current_28d_queries"],
        data["previous_28d_queries"],
    )

    yoy = year_on_year(
        data["current_90d_pages"],
        data["last_year_90d_pages"],
        data["current_90d_queries"],
        data["last_year_90d_queries"],
    )

    watchlist = fidget_ring_watchlist(
        data["current_28d_queries"],
        data["previous_28d_queries"],
    )

    seasonal = seasonal_flag(data["current_28d_queries"])

    result = {
        "month_on_month": mom,
        "year_on_year": yoy,
        "fidget_ring_watchlist": watchlist,
        "seasonal_flag": seasonal,
        "date_ranges": data["date_ranges"],
        "report_month": datetime.utcnow().strftime("%B %Y"),
    }

    print(f"  MoM clicks change:     {mom['changes']['clicks_pct']}%")
    print(f"  YoY data available:    {yoy['data_available']}")
    print(f"  Watchlist queries:     {len(watchlist)}")
    print(f"  Seasonal flag active:  {seasonal['active']}")

    return result
