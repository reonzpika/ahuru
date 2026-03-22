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

from shopify_client import blog_handle_from_shopify_url, get_seo

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
