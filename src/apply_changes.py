"""
apply_changes.py
Reads approved tasks from seo_tasks.json and applies them to the live Shopify store
via the Admin GraphQL API.

Usage:
  python src/apply_changes.py                    # apply all approved tasks
  python src/apply_changes.py --dry-run          # log what would happen, no writes
  python src/apply_changes.py --rollback <id>    # revert an applied task

Status lifecycle:
  pending → approved → applied
  pending → dismissed
  pending → expired
  applied → rolled_back
  applied → error (task left as "approved" for retry)
"""

import json
import os
import sys
import traceback
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))

from shopify_client import get_seo, update_seo

# ── Paths ─────────────────────────────────────────────────────────────────────

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
TASKS_PATH = os.path.join(REPO_ROOT, "seo_tasks.json")
TASKS_TMP = os.path.join(REPO_ROOT, ".seo_tasks.json.tmp")
LOGS_DIR = os.path.join(REPO_ROOT, "logs")

DIVIDER = "─" * 40


# ── File helpers ──────────────────────────────────────────────────────────────

def _load_tasks() -> list:
    """Load seo_tasks.json. Prints error and exits 1 if missing or malformed."""
    try:
        with open(TASKS_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Error: seo_tasks.json not found at {TASKS_PATH}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: seo_tasks.json is malformed — {e}")
        sys.exit(1)

    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        print("Error: seo_tasks.json must have a top-level 'tasks' array.")
        sys.exit(1)

    return tasks, data


def _save_tasks(data: dict) -> None:
    """Atomic write of seo_tasks.json via temp file + os.replace()."""
    with open(TASKS_TMP, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(TASKS_TMP, TASKS_PATH)


def _save_audit_log(audit_records: list) -> str:
    """Appends audit records to logs/YYYY-MM-DD-applied.json. Returns path."""
    os.makedirs(LOGS_DIR, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_path = os.path.join(LOGS_DIR, f"{date_str}-applied.json")

    existing = []
    if os.path.exists(log_path):
        try:
            with open(log_path, encoding="utf-8") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, ValueError):
            existing = []

    combined = existing + audit_records
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(combined, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return log_path


# ── Core apply logic ──────────────────────────────────────────────────────────

def apply_all(dry_run: bool = False) -> list:
    """
    Applies all approved tasks from seo_tasks.json to Shopify.
    Returns list of audit records.

    On dry_run: logs actions, saves audit, but makes no Shopify writes and
    does not update seo_tasks.json task statuses.
    """
    print(f"\nSTEP 1: Loading seo_tasks.json")
    print(DIVIDER)

    tasks, full_data = _load_tasks()
    approved = [t for t in tasks if t.get("status") == "approved"]

    if not approved:
        print("No approved tasks found.")
        sys.exit(0)

    print(f"  Found {len(approved)} approved task(s)")
    if dry_run:
        print("  Mode: DRY RUN — no writes to Shopify or seo_tasks.json")
    else:
        print("  Mode: LIVE")

    audit_records = []
    applied_count = 0
    mismatch_count = 0
    dry_run_count = 0
    error_count = 0

    print(f"\nSTEP 2: Processing tasks")
    print(DIVIDER)

    for task in tasks:
        if task.get("status") != "approved":
            continue

        task_id = task["id"]
        resource = task["resource"]
        handle = task["handle"]

        print(f"\n  Task: {task_id}")
        print(f"  Resource: {resource} / {handle}")

        applied_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        audit = {
            "task_id": task_id,
            "resource": resource,
            "handle": handle,
            "applied_at": applied_at,
            "dry_run": dry_run,
            "previous_seo_title": None,
            "previous_seo_description": None,
            "new_seo_title": task["proposed_seo_title"],
            "new_seo_description": task["proposed_seo_description"],
            "result": None,
        }

        try:
            # Fetch live current values
            print(f"  Fetching live SEO from Shopify...")
            live = get_seo(resource, handle)
            print(f"  Live title: {live['seo_title']!r}")

            audit["previous_seo_title"] = live["seo_title"]
            audit["previous_seo_description"] = live["seo_description"]

            # Mismatch check — only if previous_seo_title was already recorded
            recorded_prev = task.get("previous_seo_title")
            if recorded_prev is not None and live["seo_title"] != recorded_prev:
                print(
                    f"  Warning: Live title does not match recorded previous title.\n"
                    f"    Recorded: {recorded_prev!r}\n"
                    f"    Live:     {live['seo_title']!r}\n"
                    f"  Skipping to avoid overwriting unexpected change."
                )
                audit["result"] = "skipped_mismatch"
                mismatch_count += 1
                audit_records.append(audit)
                continue

            if dry_run:
                print(f"  [DRY RUN] Would apply:")
                print(f"    Title:       {task['proposed_seo_title']!r}")
                print(f"    Description: {task['proposed_seo_description']!r}")
                audit["result"] = "dry_run"
                dry_run_count += 1
            else:
                print(f"  Applying SEO changes...")
                update_seo(
                    resource,
                    live["id"],
                    task["proposed_seo_title"],
                    task["proposed_seo_description"],
                )
                print(f"  ✓ Applied")

                # Update task in memory
                task["status"] = "applied"
                task["applied_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                task["previous_seo_title"] = live["seo_title"]
                task["previous_seo_description"] = live["seo_description"]

                audit["result"] = "applied"
                applied_count += 1

        except Exception as e:
            print(f"  ✗ Error on {task_id}: {e}")
            traceback.print_exc()
            audit["result"] = "error"
            audit["error"] = str(e)
            error_count += 1
            # Leave task as "approved" for retry — do not update status

        audit_records.append(audit)

    # Atomic write — only if not dry run (statuses may have changed)
    if not dry_run and audit_records:
        print(f"\nSTEP 3: Writing seo_tasks.json")
        print(DIVIDER)
        _save_tasks(full_data)
        print("  ✓ seo_tasks.json updated atomically")

    # Save audit log regardless of dry run
    print(f"\nSTEP 4: Saving audit log")
    print(DIVIDER)
    log_path = _save_audit_log(audit_records)
    print(f"  ✓ Audit log: {log_path}")

    # Summary
    print(f"\n{'='*60}")
    print(f"Summary")
    print(f"{'='*60}")
    print(f"  Applied:             {applied_count}")
    print(f"  Skipped (mismatch):  {mismatch_count}")
    print(f"  Skipped (dry run):   {dry_run_count}")
    print(f"  Errors:              {error_count}")

    # Send confirmation email
    print(f"\nSTEP 5: Sending confirmation email")
    print(DIVIDER)
    try:
        from email_report import send_confirmation_email
        send_confirmation_email(audit_records)
    except Exception as e:
        print(f"  Warning: Confirmation email failed (run still counts as complete): {e}")

    return audit_records, error_count


# ── Rollback logic ────────────────────────────────────────────────────────────

def rollback_task(task_id: str, dry_run: bool = False) -> None:
    """
    Reverts an applied task to its previous SEO values.
    Requires task status == "applied" and previous_seo_title != None.
    """
    print(f"\nSTEP 1: Loading seo_tasks.json")
    print(DIVIDER)
    tasks, full_data = _load_tasks()

    task = next((t for t in tasks if t.get("id") == task_id), None)
    if not task:
        print(f"Error: Task not found: {task_id!r}")
        sys.exit(1)

    print(f"  Task: {task_id}")
    print(f"  Current status: {task.get('status')!r}")

    if task.get("status") != "applied":
        print(
            f"Error: Task must have status 'applied' to rollback. "
            f"Current status: {task.get('status')!r}"
        )
        sys.exit(1)

    if task.get("previous_seo_title") is None:
        print(
            "Error: Cannot rollback: previous values not recorded. "
            "Revert manually in Shopify."
        )
        sys.exit(1)

    resource = task["resource"]
    handle = task["handle"]
    prev_title = task["previous_seo_title"]
    prev_description = task["previous_seo_description"]

    print(f"\nSTEP 2: Fetching live values for audit")
    print(DIVIDER)
    live = get_seo(resource, handle)
    print(f"  Current live title: {live['seo_title']!r}")
    print(f"  Rollback to:        {prev_title!r}")

    applied_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    audit = {
        "task_id": task_id,
        "resource": resource,
        "handle": handle,
        "applied_at": applied_at,
        "dry_run": dry_run,
        "previous_seo_title": live["seo_title"],
        "previous_seo_description": live["seo_description"],
        "new_seo_title": prev_title,
        "new_seo_description": prev_description,
        "result": None,
    }

    print(f"\nSTEP 3: Applying rollback")
    print(DIVIDER)
    if dry_run:
        print(f"  [DRY RUN] Would restore:")
        print(f"    Title:       {prev_title!r}")
        print(f"    Description: {prev_description!r}")
        audit["result"] = "dry_run_rollback"
    else:
        update_seo(resource, live["id"], prev_title, prev_description or "")
        print(f"  ✓ Rolled back")
        task["status"] = "rolled_back"
        audit["result"] = "rolled_back"

        print(f"\nSTEP 4: Writing seo_tasks.json")
        print(DIVIDER)
        _save_tasks(full_data)
        print("  ✓ seo_tasks.json updated atomically")

    print(f"\nSTEP 5: Saving audit log")
    print(DIVIDER)
    log_path = _save_audit_log([audit])
    print(f"  ✓ Audit log: {log_path}")

    print(f"\n{'='*60}")
    print(f"Rollback complete: {task_id}")
    print(f"{'='*60}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]

    if "--rollback" in args:
        idx = args.index("--rollback")
        if idx + 1 >= len(args):
            print("Error: --rollback requires a task ID argument.")
            sys.exit(1)
        task_id = args[idx + 1]
        dry_run = "--dry-run" in args
        rollback_task(task_id, dry_run=dry_run)

    elif "--dry-run" in args:
        _, error_count = apply_all(dry_run=True)
        if error_count > 0:
            sys.exit(1)

    else:
        _, error_count = apply_all(dry_run=False)
        if error_count > 0:
            sys.exit(1)


if __name__ == "__main__":
    main()
