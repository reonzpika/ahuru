"""
Live Shopify SEO for the BEFORE column (previous_seo_title / previous_seo_description).
Values reflect Shopify at task creation or backfill time: dashboard before/after and
apply_changes mismatch checks.

Used when creating meta_update tasks in generate_changes and by backfill_previous_seo.py.
Same read path as apply_changes (shopify_client.get_seo).

Set SEO_SKIP_BASELINE_FETCH=1 (or true/yes) to skip baseline fetches in generate_changes
without removing credentials; backfill script is unaffected.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

from shopify_client import blog_handle_from_shopify_url, get_seo

# Canonical storefront URL for normalising GSC page paths
_STORE_BASE = "https://www.ahurucandles.co.nz"

_MISSING_SHOPIFY_LOGGED = False
_UNSUPPORTED_RESOURCE_LOGGED: set[tuple[str, str]] = set()


def shopify_env_ready() -> bool:
    return all(
        os.environ.get(k) for k in ("SHOPIFY_CLIENT_ID", "SHOPIFY_CLIENT_SECRET", "SHOPIFY_DOMAIN")
    )


def resolve_fetch_baseline_seo(explicit: bool | None) -> bool:
    """
    If explicit is True/False, use it. Otherwise skip when SEO_SKIP_BASELINE_FETCH is set.
    """
    if explicit is not None:
        return explicit
    v = os.environ.get("SEO_SKIP_BASELINE_FETCH", "").strip().lower()
    return v not in ("1", "true", "yes")


def get_live_seo_pair(
    resource: str,
    handle: str,
    *,
    task_id: str | None = None,
    cache: dict[tuple[str, str, str], tuple[str, str]] | None = None,
    shopify_url: str | None = None,
) -> tuple[str, str] | None:
    """
    Returns (seo_title, seo_description) from Shopify or None on skip/error.
    When cache is provided, reuses (resource, handle) within one process run.
    """
    global _MISSING_SHOPIFY_LOGGED

    if not shopify_env_ready():
        if not _MISSING_SHOPIFY_LOGGED:
            print(
                "Note: SHOPIFY_CLIENT_ID / SHOPIFY_CLIENT_SECRET / SHOPIFY_DOMAIN not all set: "
                "skipping baseline SEO fetch"
            )
            _MISSING_SHOPIFY_LOGGED = True
        return None

    if not handle or resource not in ("product", "article", "collection", "page"):
        key = (str(resource), str(handle))
        if key not in _UNSUPPORTED_RESOURCE_LOGGED:
            tid = f"{task_id!r}: " if task_id else ""
            print(
                f"Warning: Baseline SEO not fetched for {tid}"
                f"resource {resource!r} is not supported "
                f"(expected product, article, collection, or page)"
            )
            _UNSUPPORTED_RESOURCE_LOGGED.add(key)
        return None

    blog_h = blog_handle_from_shopify_url(shopify_url or "") if resource == "article" else None
    cache_key = (resource, blog_h or "", handle)
    if cache is not None and cache_key in cache:
        return cache[cache_key]

    try:
        live = get_seo(resource, handle, blog_handle=blog_h)
        title = live["seo_title"]
        desc = live["seo_description"]
    except Exception as e:
        label = task_id or f"{resource}/{handle}"
        print(f"Warning: Could not fetch baseline SEO for {label!r}: {e}")
        return None

    pair = (title, desc)
    if cache is not None:
        cache[cache_key] = pair
    return pair


def fetch_previous_seo_for_task(task: dict, cache: dict[tuple[str, str, str], tuple[str, str]]) -> None:
    """
    Mutates task in place. Only meta_update; uses get_seo for supported resources.
    Caches (resource, handle) -> (seo_title, seo_description) for one run.
    """
    if task.get("type") != "meta_update":
        return

    resource = task.get("resource")
    handle = task.get("handle")
    if not isinstance(resource, str) or not isinstance(handle, str):
        return

    pair = get_live_seo_pair(
        resource,
        handle,
        task_id=task.get("id"),
        cache=cache,
        shopify_url=task.get("shopify_url"),
    )
    if pair is None:
        return

    task["previous_seo_title"], task["previous_seo_description"] = pair


def _normalise_page_url(page: str) -> str:
    p = (page or "").strip()
    if p.startswith("http://") or p.startswith("https://"):
        return p
    if p.startswith("/"):
        return _STORE_BASE.rstrip("/") + p
    return f"{_STORE_BASE}/{p.lstrip('/')}"


def resource_handle_from_store_url(url: str) -> tuple[str, str] | None:
    """
    Map a storefront URL to (resource, handle) for get_seo.
    Returns None for paths we do not support (e.g. home, cart).
    """
    path = urlparse(url).path.rstrip("/")
    segments = [s for s in path.split("/") if s]
    if not segments:
        return None
    handle = segments[-1]
    lower = path.lower()
    if "/products/" in lower:
        return "product", handle
    if "/collections/" in lower:
        return "collection", handle
    if "/blogs/" in lower:
        return "article", handle
    if "/pages/" in lower:
        return "page", handle
    return None


def _attach_shopify_live_meta_to_row(
    row: dict,
    *,
    cache: dict[tuple[str, str, str], tuple[str, str]],
    task_prefix: str,
) -> bool:
    """
    If row has a string 'page' URL that maps to a supported Shopify resource, sets
    shopify_live_title and shopify_live_description. Returns True when fields were set.
    """
    page = row.get("page")
    if not isinstance(page, str) or not page.strip():
        return False
    url = _normalise_page_url(page)
    parsed = resource_handle_from_store_url(url)
    if not parsed:
        return False
    resource, handle = parsed
    pair = get_live_seo_pair(
        resource,
        handle,
        task_id=f"{task_prefix}:{handle}",
        cache=cache,
        shopify_url=url,
    )
    if pair is None:
        return False
    title, desc = pair
    row["shopify_live_title"] = title
    row["shopify_live_description"] = desc
    return True


def enrich_weekly_analysis_shopify(analysis: dict) -> None:
    """
    Mutates analysis in place: adds shopify_live_title / shopify_live_description to
    rows under ctr_opportunities, top_pages_90d, and each cannibalisation issue's
    competing_pages, when SHOPIFY_* env is set and the URL maps to product, collection,
    article, or page. One shared cache avoids duplicate API calls for the same resource.
    """
    if not shopify_env_ready():
        return

    cache: dict[tuple[str, str, str], tuple[str, str]] = {}
    ctr_n = top_n = cann_n = 0

    for row in analysis.get("ctr_opportunities") or []:
        if _attach_shopify_live_meta_to_row(row, cache=cache, task_prefix="ctr"):
            ctr_n += 1

    for row in analysis.get("top_pages_90d") or []:
        if _attach_shopify_live_meta_to_row(row, cache=cache, task_prefix="top"):
            top_n += 1

    for issue in analysis.get("cannibalisation") or []:
        for row in issue.get("competing_pages") or []:
            if _attach_shopify_live_meta_to_row(row, cache=cache, task_prefix="cannibal"):
                cann_n += 1

    total = ctr_n + top_n + cann_n
    if total:
        print(
            f"  Live Shopify meta for Claude: {ctr_n} CTR rows, "
            f"{top_n} top pages, {cann_n} cannibalisation URLs "
            f"({len(cache)} unique resources fetched)"
        )
