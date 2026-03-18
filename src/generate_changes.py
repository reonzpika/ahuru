"""
generate_changes.py
Extracts actionable SEO changes from the weekly report and GSC analysis.
Writes tasks to seo_tasks.json (central registry) and pending/YYYY-MM-DD-changes.json.
No Claude API — copy is parsed from the report's CTR Opportunities section.
"""

import json
import os
import re
from datetime import date, timedelta
from urllib.parse import urlparse

# ── Configuration ─────────────────────────────────────────────────────────────

SEO_TASKS_PATH = os.path.join(os.path.dirname(__file__), "..", "seo_tasks.json")
PENDING_DIR = os.path.join(os.path.dirname(__file__), "..", "pending")
BASE_URL = "https://www.ahurucandles.co.nz"

MAX_META = 5
MAX_CONTENT = 5
MAX_CANNIBAL = 3
EXPIRY_DAYS = 28

VALID_STATUSES = frozenset({
    "pending", "approved", "applied", "dismissed", "expired", "error", "rolled_back",
})
VALID_TYPES = frozenset({
    "meta_update", "content_update", "redirect", "noindex", "internal_links", "canonical",
})

MIN_TITLE_LEN = 10
MAX_TITLE_LEN = 60
MIN_DESC_LEN = 20
MAX_DESC_LEN = 155


# ── Helpers ──────────────────────────────────────────────────────────────────

def _derive_handle(url: str) -> str | None:
    """
    Extract Shopify handle from a full URL (last path segment).
    """
    path = urlparse(url).path.rstrip("/")
    segments = [s for s in path.split("/") if s]
    if not segments:
        return None
    return segments[-1]


def _infer_resource(url: str) -> str:
    if "/products/" in url:
        return "product"
    if "/collections/" in url:
        return "collection"
    if "/blogs/" in url:
        return "article"
    if "/pages/" in url:
        return "page"
    return "page"


def _parse_ctr_opportunities(report_text: str) -> dict[str, dict]:
    """
    Find ## 🟠 CTR Opportunities and extract per-URL suggested title/description.
    Returns dict keyed by handle: {handle: {"title": str, "description": str}}.
    """
    section_marker = "## 🟠 CTR Opportunities"
    idx = report_text.find(section_marker)
    if idx == -1:
        print("Warning: CTR Opportunities section not found in report — no meta_update copy")
        return {}

    section = report_text[idx:]
    # Stop at next ## heading
    next_h2 = re.search(r"\n## [^🟠]", section)
    if next_h2:
        section = section[: next_h2.start()]

    result = {}
    # Blocks: **`URL`** then list items with Suggested title / Suggested description
    block_pattern = re.compile(
        r"\*\*`([^`]+)`\*\*\s*\n"
        r"(?:.*\n)*?"
        r"- Suggested title: `([^`]*)`\s*\n"
        r"(?:.*\n)*?"
        r"- Suggested description: `([^`]*)`",
        re.MULTILINE,
    )

    for m in block_pattern.finditer(section):
        url, title, description = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
        handle = _derive_handle(url)
        if not handle:
            print(f"Warning: Could not derive handle from URL: {url}")
            continue
        if not title or not description:
            print(f"Warning: Empty title or description for {handle} — skipping")
            continue
        if len(title) < MIN_TITLE_LEN:
            print(f"Warning: Title too short for {handle} ({len(title)} chars) — skipping")
            continue
        if len(description) < MIN_DESC_LEN:
            print(f"Warning: Description too short for {handle} ({len(description)} chars) — skipping")
            continue
        if title == handle or title == url or description == handle or description == url:
            print(f"Warning: Title or description equals handle/URL for {handle} — skipping")
            continue
        if len(title) > MAX_TITLE_LEN:
            title = title[:57].rstrip() + "..."
            print(f"Warning: Title truncated to 60 chars for {handle}")
        if len(description) > MAX_DESC_LEN:
            description = description[:152].rstrip() + "..."
            print(f"Warning: Description truncated to 155 chars for {handle}")
        result[handle] = {"title": title, "description": description}

    return result


def _dominant_page_for_query(page_query_90d: list, query: str) -> str | None:
    """
    Given GSC rows with keys [page, query], return the page (keys[0]) with
    highest impressions for this query. Return None if no matching row.
    """
    best_page = None
    best_impressions = 0
    for row in page_query_90d:
        keys = row.get("keys") or []
        if len(keys) < 2:
            continue
        if keys[1] != query:
            continue
        imp = row.get("impressions", 0)
        if imp > best_impressions:
            best_impressions = imp
            best_page = keys[0]
    return best_page


def _sweep_expired(tasks: list) -> tuple[list, int]:
    """Set status to 'expired' for pending tasks past expires_date. Return (tasks, count)."""
    today = date.today().isoformat()
    count = 0
    for t in tasks:
        if t.get("status") == "pending" and t.get("expires_date") and t["expires_date"] < today:
            t["status"] = "expired"
            count += 1
    return tasks, count


def _load_seo_tasks() -> tuple[dict | None, list | None]:
    """
    Read seo_tasks.json. If missing, return ({"version": "1", "tasks": []}, []).
    If malformed, log and return (None, None).
    """
    if not os.path.exists(SEO_TASKS_PATH):
        return {"version": "1", "tasks": []}, []

    try:
        with open(SEO_TASKS_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: seo_tasks.json is malformed — {e}. Aborting generate_changes.")
        return None, None

    if not isinstance(data, dict) or "tasks" not in data:
        print("Error: seo_tasks.json has invalid structure. Aborting generate_changes.")
        return None, None

    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        tasks = []
    return data, tasks


def _build_active_index(tasks: list) -> set:
    """Task IDs that are pending, approved, or applied (block new duplicate IDs)."""
    return {t["id"] for t in tasks if t.get("status") in ("pending", "approved", "applied")}


def _build_dismissed_dict(tasks: list) -> dict:
    """Dict of task_id -> task for dismissed tasks (for re-surface logic)."""
    return {t["id"]: t for t in tasks if t.get("status") == "dismissed"}


def _make_task(
    task_id: str,
    task_type: str,
    resource: str,
    handle: str,
    shopify_url: str,
    auto_apply: bool,
    priority: int,
    report_date: str,
    *,
    previous_seo_title: str = "",
    previous_seo_description: str = "",
    proposed_seo_title: str = "",
    proposed_seo_description: str = "",
    impressions_at_creation: int = 0,
    ctr_at_creation: float = 0.0,
    position_at_creation: float = 0.0,
    notes: str = "",
) -> dict:
    """Build one task dict with full schema. report_date is the pipeline run date."""
    created = report_date
    exp = (date.fromisoformat(created) + timedelta(days=EXPIRY_DAYS)).isoformat()
    return {
        "id": task_id,
        "type": task_type,
        "resource": resource,
        "handle": handle,
        "shopify_url": shopify_url,
        "status": "pending",
        "auto_apply": auto_apply,
        "priority": priority,
        "created_date": created,
        "expires_date": exp,
        "approved_date": None,
        "applied_date": None,
        "dismissed_date": None,
        "previous_seo_title": previous_seo_title or "",
        "previous_seo_description": previous_seo_description or "",
        "proposed_seo_title": proposed_seo_title or "",
        "proposed_seo_description": proposed_seo_description or "",
        "impressions_at_creation": impressions_at_creation,
        "ctr_at_creation": ctr_at_creation,
        "position_at_creation": position_at_creation,
        "dismissal_threshold_impressions": None,
        "report_date": report_date,
        "notes": notes or "",
    }


# ── Entry point ─────────────────────────────────────────────────────────────

def generate_changes(
    analysis: dict,
    report_text: str,
    page_query_90d: list | None = None,
    report_date: str | None = None,
) -> int:
    """
    Sweep expired tasks, build new tasks from analysis + report copy, append to
    seo_tasks.json and write pending/YYYY-MM-DD-changes.json.
    Returns number of new tasks created.
    """
    page_query_90d = page_query_90d or []
    report_date = report_date or date.today().isoformat()

    # ── Step 1: Sweep expired ─────────────────────────────────────────────────
    loaded = _load_seo_tasks()
    if loaded[0] is None:
        return 0

    structure, tasks = loaded
    tasks, expired_count = _sweep_expired(tasks)
    structure["tasks"] = tasks

    if expired_count > 0:
        # Atomic write of swept file
        tasks_dir = os.path.dirname(SEO_TASKS_PATH)
        os.makedirs(tasks_dir, exist_ok=True)
        tmp_path = os.path.join(tasks_dir, ".seo_tasks.json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(structure, f, indent=2)
        os.replace(tmp_path, SEO_TASKS_PATH)
        print(f"Expired {expired_count} stale pending tasks")

    # ── Step 2: Index ────────────────────────────────────────────────────────
    active_index = _build_active_index(tasks)
    dismissed_dict = _build_dismissed_dict(tasks)

    # ── Step 3: Copy from report ─────────────────────────────────────────────
    ctr_copy = _parse_ctr_opportunities(report_text)

    # ── Step 4 & 5: Build new tasks ──────────────────────────────────────────
    new_tasks = []
    skipped_active = 0
    skipped_no_copy = 0
    skipped_no_page = 0

    # meta_update from ctr_opportunities (sorted by impressions desc)
    ctr_items = sorted(
        analysis.get("ctr_opportunities", []),
        key=lambda x: x.get("impressions", 0),
        reverse=True,
    )
    for item in ctr_items[: MAX_META * 2]:  # iterate more, cap at MAX_META
        if len([t for t in new_tasks if t["type"] == "meta_update"]) >= MAX_META:
            break
        page = item.get("page") or ""
        handle = _derive_handle(page)
        if not handle:
            print(f"Warning: Could not derive handle from ctr_opportunity: {page}")
            continue
        task_id = f"meta_update__{handle}"
        if task_id in active_index:
            skipped_active += 1
            continue
        copy_data = ctr_copy.get(handle)
        if not copy_data:
            skipped_no_copy += 1
            continue
        # Re-surface: skip (do not re-surface) when current impressions < threshold * 1.5;
        # re-surface (create new task) only when current impressions >= threshold * 1.5.
        dismissed = dismissed_dict.get(task_id)
        if dismissed and dismissed.get("dismissal_threshold_impressions") is not None:
            threshold = dismissed["dismissal_threshold_impressions"] * 1.5
            if item.get("impressions", 0) < threshold:
                skipped_active += 1
                continue
        resource = _infer_resource(page)
        task = _make_task(
            task_id=task_id,
            task_type="meta_update",
            resource=resource,
            handle=handle,
            shopify_url=page if page.startswith("http") else f"{BASE_URL}{page}" if page.startswith("/") else f"{BASE_URL}/{resource}s/{handle}",
            auto_apply=True,
            priority=0,  # assigned later
            report_date=report_date,
            previous_seo_title="",
            previous_seo_description="",
            proposed_seo_title=copy_data["title"],
            proposed_seo_description=copy_data["description"],
            impressions_at_creation=item.get("impressions", 0),
            ctr_at_creation=item.get("ctr_pct", 0) or 0,
            position_at_creation=item.get("avg_position", 0) or 0,
            notes="",
        )
        # Normalise shopify_url if we only had path
        if not task["shopify_url"].startswith("http"):
            task["shopify_url"] = BASE_URL + ("/" + page.lstrip("/") if page.startswith("/") else f"/{resource}s/{handle}")
        new_tasks.append(task)

    # content_update from quick_wins (handle from page_query_90d)
    qw_items = sorted(
        analysis.get("quick_wins", []),
        key=lambda x: x.get("impressions", 0),
        reverse=True,
    )
    for item in qw_items:
        if len([t for t in new_tasks if t["type"] == "content_update"]) >= MAX_CONTENT:
            break
        query = item.get("query") or ""
        if not query:
            continue
        dominant_page = _dominant_page_for_query(page_query_90d, query)
        if not dominant_page:
            skipped_no_page += 1
            continue
        handle = _derive_handle(dominant_page)
        if not handle:
            skipped_no_page += 1
            continue
        task_id = f"content_update__{handle}"
        if task_id in active_index:
            skipped_active += 1
            continue
        position = item.get("avg_position") or 0
        impressions = item.get("impressions") or 0
        notes = f"Position {position} with {impressions} impressions — content update needed to reach page 1"
        resource = _infer_resource(dominant_page)
        shopify_url = dominant_page if dominant_page.startswith("http") else BASE_URL + (dominant_page if dominant_page.startswith("/") else f"/{resource}s/{handle}")
        task = _make_task(
            task_id=task_id,
            task_type="content_update",
            resource=resource,
            handle=handle,
            shopify_url=shopify_url,
            auto_apply=False,
            priority=0,
            report_date=report_date,
            impressions_at_creation=impressions,
            ctr_at_creation=item.get("ctr_pct") or 0,
            position_at_creation=position,
            notes=notes,
        )
        new_tasks.append(task)

    # cannibalisation: always type canonical
    cannib_items = sorted(
        analysis.get("cannibalisation", []),
        key=lambda x: x.get("total_impressions", 0),
        reverse=True,
    )
    for item in cannib_items[:MAX_CANNIBAL]:
        if len([t for t in new_tasks if t["type"] == "canonical"]) >= MAX_CANNIBAL:
            break
        competing = item.get("competing_pages") or []
        if not competing:
            continue
        dominant = competing[0]
        page = dominant.get("page") or ""
        handle = _derive_handle(page)
        if not handle:
            continue
        task_id = f"canonical__{handle}"
        if task_id in active_index:
            skipped_active += 1
            continue
        query = item.get("query") or ""
        page_count = item.get("page_count") or 0
        total_impressions = item.get("total_impressions") or 0
        notes = f"{page_count} pages competing for '{query}' — {total_impressions} total impressions"
        resource = _infer_resource(page)
        shopify_url = page if page.startswith("http") else BASE_URL + (page if page.startswith("/") else f"/{resource}s/{handle}")
        task = _make_task(
            task_id=task_id,
            task_type="canonical",
            resource=resource,
            handle=handle,
            shopify_url=shopify_url,
            auto_apply=False,
            priority=0,
            report_date=report_date,
            impressions_at_creation=dominant.get("impressions", 0),
            notes=notes,
        )
        new_tasks.append(task)

    # ── Step 6: Assign priority ───────────────────────────────────────────────
    type_order = {"meta_update": 0, "content_update": 1, "canonical": 2}
    new_tasks.sort(
        key=lambda t: (type_order.get(t["type"], 3), -t.get("impressions_at_creation", 0)),
    )
    for i, t in enumerate(new_tasks, start=1):
        t["priority"] = i

    # ── Step 7: Atomic write seo_tasks.json, then pending manifest ───────────
    if new_tasks:
        structure["tasks"] = tasks + new_tasks
        tasks_dir = os.path.dirname(SEO_TASKS_PATH)
        os.makedirs(tasks_dir, exist_ok=True)
        tmp_path = os.path.join(tasks_dir, ".seo_tasks.json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(structure, f, indent=2)
        os.replace(tmp_path, SEO_TASKS_PATH)

        os.makedirs(PENDING_DIR, exist_ok=True)
        pending_path = os.path.join(PENDING_DIR, f"{report_date}-changes.json")
        with open(pending_path, "w", encoding="utf-8") as f:
            json.dump(new_tasks, f, indent=2)

    # ── Step 8: Summary ───────────────────────────────────────────────────────
    print(f"  New tasks created:   {len(new_tasks)}")
    print(f"  Expired tasks swept: {expired_count}")
    print(f"  Skipped (active):    {skipped_active}")
    print(f"  Skipped (no copy):   {skipped_no_copy}")
    if skipped_no_page:
        print(f"  Skipped (no page for query): {skipped_no_page}")

    return len(new_tasks)
