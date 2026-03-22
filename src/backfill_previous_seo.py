"""
One-off backfill: set previous_seo_title / previous_seo_description on meta_update tasks
where both are missing, for pending or approved rows only (not applied; live store would
no longer reflect pre-apply baseline).

Usage:
  python src/backfill_previous_seo.py              # dry-run (default)
  python src/backfill_previous_seo.py --write      # update seo_tasks.json atomically

Requires SHOPIFY_CLIENT_ID, SHOPIFY_CLIENT_SECRET, SHOPIFY_DOMAIN (e.g. via .env).
"""

from __future__ import annotations

import json
import os
import sys

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
TASKS_PATH = os.path.join(REPO_ROOT, "seo_tasks.json")
TASKS_TMP = os.path.join(REPO_ROOT, ".seo_tasks.json.tmp")

sys.path.insert(0, os.path.dirname(__file__))

from baseline_seo import get_live_seo_pair  # noqa: E402


def _prev_empty(v) -> bool:
    return v is None or v == ""


def _should_backfill(task: dict) -> bool:
    if task.get("type") != "meta_update":
        return False
    if task.get("status") not in ("pending", "approved"):
        return False
    return _prev_empty(task.get("previous_seo_title")) and _prev_empty(task.get("previous_seo_description"))


def main() -> int:
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        return 0
    write = "--write" in sys.argv
    extra = [a for a in sys.argv[1:] if a not in ("--write",)]
    if extra:
        print(f"Unknown arguments: {extra}")
        return 2

    try:
        with open(TASKS_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Error: {TASKS_PATH} not found")
        return 1
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON — {e}")
        return 1

    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        print("Error: tasks must be a list")
        return 1

    cache: dict[tuple[str, str, str], tuple[str, str]] = {}
    candidates = [t for t in tasks if isinstance(t, dict) and _should_backfill(t)]
    updated = 0
    errors = 0
    skipped_unsupported = 0

    mode = "WRITE" if write else "DRY RUN"
    print(f"backfill_previous_seo.py — {mode}")
    print(f"Candidates: {len(candidates)}\n")

    for task in candidates:
        tid = task.get("id", "?")
        resource = task.get("resource")
        handle = task.get("handle")
        if not isinstance(resource, str) or not isinstance(handle, str):
            print(f"  skip {tid!r}: missing resource or handle")
            skipped_unsupported += 1
            continue

        pair = get_live_seo_pair(
            resource,
            handle,
            task_id=tid,
            cache=cache,
            shopify_url=task.get("shopify_url"),
        )
        if pair is None:
            errors += 1
            continue

        title, desc = pair
        t_short = (title[:56] + "…") if len(title) > 56 else title
        d_short = (desc[:56] + "…") if len(desc) > 56 else desc
        print(f"  {tid}")
        print(f"    previous_seo_title:       {t_short!r}")
        print(f"    previous_seo_description: {d_short!r}")

        if write:
            task["previous_seo_title"] = title
            task["previous_seo_description"] = desc
        updated += 1

    print()
    print(f"Summary: candidates={len(candidates)}, would_update={updated}, errors={errors}, skipped_bad_shape={skipped_unsupported}")

    if write and updated > 0:
        with open(TASKS_TMP, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(TASKS_TMP, TASKS_PATH)
        print(f"Wrote {TASKS_PATH} atomically")
    elif write:
        print("No changes written")
    else:
        print("Dry run only — pass --write to save")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
