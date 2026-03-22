"""
email_report.py
Builds a short HTML email (report highlights) and sends via Resend.
Full Markdown lives on the GitHub Pages dashboard; the email links there.

From:    ahuru-seo-report@clinicpro.co.nz
To:      info@ahurucandles.com, ryo@clinicpro.co.nz
Trigger: called from run_weekly.py / run_monthly.py after save_report()
"""

import os
import re
from datetime import datetime, timezone

import json
import requests as _requests


# ── Configuration ─────────────────────────────────────────────────────────────

RESEND_API_URL = "https://api.resend.com/emails"
FROM_ADDRESS   = "Āhuru SEO Report <ahuru-seo-report@clinicpro.co.nz>"
TO_ADDRESSES   = ["info@ahurucandles.com", "ryo@clinicpro.co.nz"]

# Full Markdown reports are published on GitHub Pages; email sends highlights only.
DASHBOARD_REPORT_URL = "https://reonzpika.github.io/ahuru/dashboard.html"


# ── Markdown → HTML ───────────────────────────────────────────────────────────

def markdown_to_html(md):
    """
    Converts the report Markdown to clean HTML for email.
    Handles the specific formatting patterns in our report.
    Deliberately simple — no external dependencies.
    """
    lines = md.split("\n")
    html_lines = []
    in_table = False
    in_code = False
    i = 0

    while i < len(lines):
        line = lines[i]

        # ── Code blocks ──────────────────────────────────────────
        if line.strip().startswith("```"):
            if not in_code:
                in_code = True
                html_lines.append('<pre style="background:#1e1e2e;color:#cdd6f4;padding:12px 16px;border-radius:6px;font-size:13px;overflow-x:auto;margin:12px 0;">')
            else:
                in_code = False
                html_lines.append("</pre>")
            i += 1
            continue

        if in_code:
            # Escape HTML inside code blocks
            safe = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            html_lines.append(safe + "\n")
            i += 1
            continue

        # ── Tables ───────────────────────────────────────────────
        if line.strip().startswith("|"):
            # Skip separator rows (|---|---|)
            if re.match(r"^\|[-| :]+\|$", line.strip()):
                i += 1
                continue
            if not in_table:
                in_table = True
                html_lines.append(
                    '<table style="width:100%;border-collapse:collapse;margin:16px 0;font-size:14px;">'
                )
                # First table row is the header
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                html_lines.append("<thead><tr>")
                for cell in cells:
                    html_lines.append(
                        f'<th style="text-align:left;padding:8px 12px;background:#1e3a5f;color:#ffffff;border:1px solid #2d5a9e;">{_inline(cell)}</th>'
                    )
                html_lines.append("</tr></thead><tbody>")
            else:
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                html_lines.append("<tr>")
                for cell in cells:
                    html_lines.append(
                        f'<td style="padding:8px 12px;border:1px solid #e2e8f0;vertical-align:top;">{_inline(cell)}</td>'
                    )
                html_lines.append("</tr>")
            i += 1
            continue
        else:
            if in_table:
                in_table = False
                html_lines.append("</tbody></table>")

        # ── Headings ─────────────────────────────────────────────
        if line.startswith("#### "):
            html_lines.append(f'<h4 style="color:#1e3a5f;margin:16px 0 8px;">{_inline(line[5:])}</h4>')
        elif line.startswith("### "):
            html_lines.append(f'<h3 style="color:#1e3a5f;margin:20px 0 8px;">{_inline(line[4:])}</h3>')
        elif line.startswith("## "):
            html_lines.append(f'<h2 style="color:#1e3a5f;border-bottom:2px solid #2d5a9e;padding-bottom:6px;margin:28px 0 12px;">{_inline(line[3:])}</h2>')
        elif line.startswith("# "):
            html_lines.append(f'<h1 style="color:#1e3a5f;margin:0 0 4px;">{_inline(line[2:])}</h1>')

        # ── Horizontal rule ──────────────────────────────────────
        elif line.strip() == "---":
            html_lines.append('<hr style="border:none;border-top:1px solid #e2e8f0;margin:20px 0;">')

        # ── List items ───────────────────────────────────────────
        elif line.strip().startswith("- "):
            html_lines.append(
                f'<li style="margin:4px 0;padding-left:4px;">{_inline(line.strip()[2:])}</li>'
            )

        # ── Blank lines ──────────────────────────────────────────
        elif line.strip() == "":
            html_lines.append("<br>")

        # ── Normal paragraph ─────────────────────────────────────
        else:
            html_lines.append(f'<p style="margin:6px 0;line-height:1.6;">{_inline(line)}</p>')

        i += 1

    # Close any open table
    if in_table:
        html_lines.append("</tbody></table>")

    return "\n".join(html_lines)


def _inline(text):
    """Process inline Markdown: bold, italic, inline code, links."""
    # Inline code — must come before bold/italic
    text = re.sub(
        r"`([^`]+)`",
        r'<code style="background:#f1f5f9;padding:2px 5px;border-radius:3px;font-family:monospace;font-size:13px;">\1</code>',
        text,
    )
    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # Italic
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    # Links
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2" style="color:#2d5a9e;">\1</a>',
        text,
    )
    # Plain URLs
    text = re.sub(
        r"(?<![\"'=])(https?://[^\s<>\"]+)",
        r'<a href="\1" style="color:#2d5a9e;word-break:break-all;">\1</a>',
        text,
    )
    return text


# ── Teaser (highlights) for email ─────────────────────────────────────────────


def extract_teaser_markdown(md: str, *, max_h2_sections: int = 2, max_chars: int = 4500) -> str:
    """
    Returns the start of the report: title, intro, and the first N top-level ## sections.
    Avoids emailing the full Markdown; the dashboard hosts the complete file.
    """
    if not md or not md.strip():
        return md
    lines = md.split("\n")
    out: list[str] = []
    h2_count = 0
    for line in lines:
        if re.match(r"^## [^#]", line):
            h2_count += 1
            if h2_count > max_h2_sections:
                break
        out.append(line)
    teaser = "\n".join(out).strip()
    if len(teaser) > max_chars:
        teaser = teaser[:max_chars]
        cut = teaser.rfind("\n")
        if cut > max_chars // 2:
            teaser = teaser[:cut]
        teaser = teaser.rstrip() + "\n\n_(Truncated. Full report on the dashboard.)_"
    return teaser


# ── HTML wrapper ──────────────────────────────────────────────────────────────

def wrap_html(body_html, report_date, summary, *, dashboard_url: str = DASHBOARD_REPORT_URL):
    """Wraps the report body in a full HTML email template (highlights + dashboard CTA)."""

    clicks_wow = summary.get("clicks_wow_pct")
    impr_wow   = summary.get("impressions_wow_pct")

    def fmt_change(val):
        if val is None:
            return "—"
        arrow = "▲" if val > 0 else "▼"
        colour = "#16a34a" if val > 0 else "#dc2626"
        return f'<span style="color:{colour};font-weight:bold;">{arrow} {abs(val)}%</span>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Āhuru SEO Report: {report_date}</title>
</head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#1a202c;">

  <div style="max-width:680px;margin:32px auto;background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.1);">

    <!-- Header -->
    <div style="background:#1e3a5f;padding:28px 32px;">
      <p style="margin:0;color:#93c5fd;font-size:12px;text-transform:uppercase;letter-spacing:1px;">{summary.get('_report_type', 'weekly').capitalize()} SEO Report</p>
      <h1 style="margin:4px 0 0;color:#ffffff;font-size:22px;">Āhuru Candles</h1>
      <p style="margin:6px 0 0;color:#93c5fd;font-size:14px;">{report_date}</p>
    </div>

    <!-- KPI strip -->
    <div style="display:flex;background:#f1f5f9;padding:0;">
      <div style="flex:1;padding:16px 20px;border-right:1px solid #e2e8f0;text-align:center;">
        <p style="margin:0;font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;">Clicks (7d)</p>
        <p style="margin:4px 0 0;font-size:22px;font-weight:700;color:#1e3a5f;">{summary.get("current_7d_clicks", "—"):,}</p>
        <p style="margin:2px 0 0;font-size:12px;">{fmt_change(clicks_wow)} vs last week</p>
      </div>
      <div style="flex:1;padding:16px 20px;border-right:1px solid #e2e8f0;text-align:center;">
        <p style="margin:0;font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;">Impressions (7d)</p>
        <p style="margin:4px 0 0;font-size:22px;font-weight:700;color:#1e3a5f;">{summary.get("current_7d_impressions", "—"):,}</p>
        <p style="margin:2px 0 0;font-size:12px;">{fmt_change(impr_wow)} vs last week</p>
      </div>
      <div style="flex:1;padding:16px 20px;text-align:center;">
        <p style="margin:0;font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;">Clicks (90d)</p>
        <p style="margin:4px 0 0;font-size:22px;font-weight:700;color:#1e3a5f;">{summary.get("total_clicks_90d", "—"):,}</p>
        <p style="margin:2px 0 0;font-size:12px;color:#64748b;">{summary.get("ranked_pages_90d", "—")} ranked pages</p>
      </div>
    </div>

    <!-- Highlights notice + dashboard CTA -->
    <div style="margin:0;padding:20px 32px 0;">
      <div style="background:#fffbeb;border-left:4px solid #d97706;padding:16px 20px;border-radius:0 8px 8px 0;">
        <p style="margin:0 0 8px;font-weight:bold;color:#92400e;font-size:14px;">Highlights only</p>
        <p style="margin:0;font-size:14px;line-height:1.55;color:#78350f;">
          This email is a short extract. The full Markdown report (and archives) lives on the dashboard under
          <strong>SEO reports</strong>. You only need a GitHub token for tasks, not for reading the report.
        </p>
        <p style="margin:14px 0 0;">
          <a href="{dashboard_url}" style="display:inline-block;background:#5c0f12;color:#ffffff;padding:10px 22px;border-radius:999px;text-decoration:none;font-weight:700;font-size:14px;">Open full report</a>
        </p>
      </div>
    </div>

    <!-- Report body (teaser) -->
    <div style="padding:28px 32px;">
      {body_html}
    </div>

    <div style="padding:0 32px 28px;">
      <p style="margin:0;text-align:center;">
        <a href="{dashboard_url}" style="color:#2d5a9e;font-weight:600;font-size:15px;">Read the complete report on the dashboard</a>
      </p>
    </div>

    <!-- Footer -->
    <div style="background:#f1f5f9;padding:16px 32px;border-top:1px solid #e2e8f0;">
      <p style="margin:0;font-size:12px;color:#94a3b8;text-align:center;">
        Generated automatically by the Āhuru SEO pipeline ·
        <a href="https://github.com/reonzpika/ahuru" style="color:#64748b;">View repo</a>
        · <a href="{dashboard_url}" style="color:#64748b;">Dashboard</a>
      </p>
    </div>

  </div>
</body>
</html>"""


# ── Send via Resend ───────────────────────────────────────────────────────────

def send_report(report_text, summary):
    """
    Sends a highlights email via Resend: first part of the Markdown plus KPI strip,
    with links to the full report on the GitHub Pages dashboard.

    Args:
        report_text: Full Markdown string of the report (teaser is derived from this)
        summary:     Dict from analyse() with click/impression stats
    """
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        raise EnvironmentError("RESEND_API_KEY environment variable is not set.")

    report_date = datetime.now(timezone.utc).strftime("%d %B %Y")

    teaser_md = extract_teaser_markdown(report_text)
    print("Converting teaser Markdown to HTML...")
    body_html = markdown_to_html(teaser_md)
    full_html = wrap_html(body_html, report_date, summary, dashboard_url=DASHBOARD_REPORT_URL)

    # Plain text: teaser + dashboard link
    plain_text = re.sub(r"[#*`]", "", teaser_md)
    plain_text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", plain_text)
    plain_text = (
        plain_text.strip()
        + "\n\n---\nFull report (all sections and archives): "
        + DASHBOARD_REPORT_URL
        + "\n"
    )

    report_type = summary.get("_report_type", "weekly")
    report_month = summary.get("_report_month", "")
    if report_type == "monthly":
        subject = f"Āhuru SEO Monthly Report (highlights): {report_month}"
    else:
        subject = f"Āhuru SEO Weekly Report (highlights): {report_date}"

    payload = {
        "from": FROM_ADDRESS,
        "to": TO_ADDRESSES,
        "subject": subject,
        "html": full_html,
        "text": plain_text,
    }

    print(f"Sending to: {', '.join(TO_ADDRESSES)}")
    print(f"Subject: {subject}")

    response = _requests.post(
        RESEND_API_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )

    if response.status_code == 200 or response.status_code == 201:
        result = response.json()
        print(f"✓ Email sent: ID {result.get('id', 'unknown')}")
        return result
    else:
        raise RuntimeError(f"Resend API error {response.status_code}: {response.text}")


# ── Approval email (pending changes manifest) ─────────────────────────────────

def _load_manifest(manifest_path):
    """Read and parse manifest JSON. Raises RuntimeError if file missing or invalid."""
    try:
        with open(manifest_path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise RuntimeError(f"Manifest file not found: {manifest_path}")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Manifest JSON invalid: {e}")
    if not isinstance(data, list):
        raise RuntimeError("Manifest must be a JSON array")
    return data


def _escape(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _ready_to_apply_rows(tasks):
    """Table rows for auto_apply True: Priority, Handle, Proposed SEO Title, Proposed Description, Impressions, CTR."""
    rows = []
    for c in tasks:
        priority = c.get("priority", "")
        handle = _escape(c.get("handle", ""))
        title = _escape(c.get("proposed_seo_title", ""))
        desc = _escape(c.get("proposed_seo_description", ""))
        imp = c.get("impressions_at_creation", 0)
        ctr = c.get("ctr_at_creation")
        ctr_str = f"{ctr}%" if ctr is not None else "—"
        rows.append(
            f"<tr><td style=\"padding:8px 12px;border:1px solid #e2e8f0;\">{priority}</td>"
            f"<td style=\"padding:8px 12px;border:1px solid #e2e8f0;\">{handle}</td>"
            f"<td style=\"padding:8px 12px;border:1px solid #e2e8f0;\">{title}</td>"
            f"<td style=\"padding:8px 12px;border:1px solid #e2e8f0;\">{desc}</td>"
            f"<td style=\"padding:8px 12px;border:1px solid #e2e8f0;\">{imp:,}</td>"
            f"<td style=\"padding:8px 12px;border:1px solid #e2e8f0;\">{ctr_str}</td></tr>"
        )
    return "\n".join(rows)


def _for_awareness_rows(tasks):
    """Table rows for auto_apply False: Priority, Handle, Type, Notes."""
    rows = []
    for c in tasks:
        priority = c.get("priority", "")
        handle = _escape(c.get("handle", ""))
        task_type = _escape(c.get("type", ""))
        notes = _escape(c.get("notes", ""))
        rows.append(
            f"<tr><td style=\"padding:8px 12px;border:1px solid #e2e8f0;\">{priority}</td>"
            f"<td style=\"padding:8px 12px;border:1px solid #e2e8f0;\">{handle}</td>"
            f"<td style=\"padding:8px 12px;border:1px solid #e2e8f0;\">{task_type}</td>"
            f"<td style=\"padding:8px 12px;border:1px solid #e2e8f0;\">{notes}</td></tr>"
        )
    return "\n".join(rows)


def _approval_email_html(manifest_filename, changes, report_date, backlog_pending_count):
    """Build full HTML body for the approval email (new task schema)."""
    auto_true = [c for c in changes if c.get("auto_apply") is True]
    auto_false = [c for c in changes if c.get("auto_apply") is False]
    table_style = "width:100%;border-collapse:collapse;margin:16px 0;font-size:14px;"
    th_style = "text-align:left;padding:8px 12px;background:#1e3a5f;color:#ffffff;border:1px solid #2d5a9e;"
    header_ready = (
        f"<tr><th style=\"{th_style}\">Priority</th><th style=\"{th_style}\">Handle</th>"
        f"<th style=\"{th_style}\">Proposed SEO Title</th><th style=\"{th_style}\">Proposed Description</th>"
        f"<th style=\"{th_style}\">Impressions</th><th style=\"{th_style}\">CTR</th></tr>"
    )
    header_awareness = (
        f"<tr><th style=\"{th_style}\">Priority</th><th style=\"{th_style}\">Handle</th>"
        f"<th style=\"{th_style}\">Type</th><th style=\"{th_style}\">Notes</th></tr>"
    )
    section1 = ""
    if auto_true:
        section1 = f"""
        <h3 style="color:#1e3a5f;margin:20px 0 8px;">Ready to apply</h3>
        <p style="margin:6px 0;line-height:1.6;">These meta updates can be applied programmatically once approved.</p>
        <table style="{table_style}"><thead>{header_ready}</thead><tbody>{_ready_to_apply_rows(auto_true)}</tbody></table>
        """
    section2 = ""
    if auto_false:
        section2 = f"""
        <h3 style="color:#1e3a5f;margin:20px 0 8px;">For your awareness</h3>
        <p style="margin:6px 0;line-height:1.6;">These require manual content or structural changes; included for tracking only.</p>
        <table style="{table_style}"><thead>{header_awareness}</thead><tbody>{_for_awareness_rows(auto_false)}</tbody></table>
        """
    backlog_line = f"<p style=\"margin:0 0 16px;line-height:1.6;\">{backlog_pending_count} tasks pending approval in seo_tasks.json.</p>" if backlog_pending_count is not None else ""
    seo_tasks_url = "https://github.com/reonzpika/ahuru/blob/main/seo_tasks.json"
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Āhuru SEO Tasks</title></head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#1a202c;">
  <div style="max-width:680px;margin:32px auto;background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.1);">
    <div style="background:#1e3a5f;padding:28px 32px;">
      <p style="margin:0;color:#93c5fd;font-size:12px;text-transform:uppercase;letter-spacing:1px;">SEO Tasks</p>
      <h1 style="margin:4px 0 0;color:#ffffff;font-size:22px;">Āhuru Candles</h1>
      <p style="margin:6px 0 0;color:#93c5fd;font-size:14px;">{report_date}</p>
    </div>
    <div style="padding:28px 32px;">
      <p style="margin:0 0 16px;font-weight:bold;">Manifest: <code style="background:#f1f5f9;padding:2px 6px;border-radius:3px;">{manifest_filename}</code></p>
      {backlog_line}
      {section1}
      {section2}
      <hr style="border:none;border-top:1px solid #e2e8f0;margin:20px 0;">
      <p style="margin:12px 0;line-height:1.6;">Auto-apply workflow coming in Phase 3. For now, review <code style="background:#f1f5f9;padding:2px 6px;">seo_tasks.json</code> in the repo.</p>
      <p style="margin:8px 0;"><a href="{seo_tasks_url}" style="color:#2d5a9e;">seo_tasks.json on GitHub</a></p>
    </div>
    <div style="background:#f1f5f9;padding:16px 32px;border-top:1px solid #e2e8f0;">
      <p style="margin:0;font-size:12px;color:#94a3b8;text-align:center;">Generated by Āhuru SEO pipeline · <a href="https://github.com/reonzpika/ahuru" style="color:#64748b;">View repo</a></p>
    </div>
  </div>
</body>
</html>"""


def _backlog_pending_count(manifest_path):
    """Count tasks with status 'pending' in seo_tasks.json (repo root)."""
    repo_root = os.path.dirname(os.path.dirname(manifest_path))
    seo_tasks_path = os.path.join(repo_root, "seo_tasks.json")
    try:
        with open(seo_tasks_path, encoding="utf-8") as f:
            data = json.load(f)
        tasks = data.get("tasks") or []
        return sum(1 for t in tasks if t.get("status") == "pending")
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def send_approval_email(manifest_path, new_task_count):
    """
    Sends (or prints) the SEO tasks approval email.
    Reads manifest from manifest_path; new_task_count is the number of new tasks this week.
    If RESEND_API_KEY is not set, prints summary to stdout and returns without error.
    """
    changes = _load_manifest(manifest_path)
    manifest_filename = os.path.basename(manifest_path)
    report_date = datetime.now(timezone.utc).strftime("%d %B %Y")
    backlog_count = _backlog_pending_count(manifest_path)

    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        print(f"RESEND_API_KEY not set — approval summary for {manifest_filename}:")
        print(f"  New tasks this week: {new_task_count}")
        print(f"  Tasks in manifest: {len(changes)}")
        if backlog_count is not None:
            print(f"  Tasks pending approval in seo_tasks.json: {backlog_count}")
        auto_true = [c for c in changes if c.get("auto_apply") is True]
        auto_false = [c for c in changes if c.get("auto_apply") is False]
        print(f"  Ready to apply: {len(auto_true)}")
        print(f"  For your awareness: {len(auto_false)}")
        return

    subject = f"Āhuru SEO Tasks — {new_task_count} new this week — {report_date}"
    body_html = _approval_email_html(manifest_filename, changes, report_date, backlog_count)
    plain_lines = [
        f"Manifest: {manifest_filename}",
        f"{new_task_count} new tasks this week.",
        f"Total in manifest: {len(changes)}",
    ]
    if backlog_count is not None:
        plain_lines.append(f"{backlog_count} tasks pending approval in seo_tasks.json.")
    plain_lines.append("Auto-apply workflow coming in Phase 3. Review seo_tasks.json in the repo.")
    plain_lines.append("https://github.com/reonzpika/ahuru/blob/main/seo_tasks.json")

    payload = {
        "from": FROM_ADDRESS,
        "to": TO_ADDRESSES,
        "subject": subject,
        "html": body_html,
        "text": "\n".join(plain_lines),
    }
    print(f"Sending approval email to: {', '.join(TO_ADDRESSES)}")
    print(f"Subject: {subject}")
    response = _requests.post(
        RESEND_API_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    if response.status_code in (200, 201):
        print(f"✓ Approval email sent — ID: {response.json().get('id', 'unknown')}")
        return response.json()
    raise RuntimeError(f"Resend API error {response.status_code}: {response.text}")


# ── Confirmation email (applied changes) ──────────────────────────────────────

def _confirmation_email_html(audit_records: list, report_date: str, log_filename: str) -> str:
    """Builds HTML body for the applied changes confirmation email."""

    def _result_style(result):
        if result == "error":
            return "background:#fee2e2;color:#991b1b;"
        if result == "skipped_mismatch":
            return "background:#fef9c3;color:#854d0e;"
        if result in ("dry_run", "dry_run_rollback"):
            return "background:#f0f9ff;color:#0369a1;"
        if result == "rolled_back":
            return "background:#f5f3ff;color:#6d28d9;"
        return "background:#dcfce7;color:#166534;"

    rows_html = ""
    for r in audit_records:
        prev_title = _escape(r.get("previous_seo_title") or "—")
        new_title = _escape(r.get("new_seo_title") or "—")
        result = r.get("result", "unknown")
        style = _result_style(result)
        rows_html += f"""
        <tr>
          <td style="padding:10px 12px;border-bottom:1px solid #e2e8f0;font-size:13px;color:#334155;font-family:monospace;">{_escape(r.get("handle", ""))}</td>
          <td style="padding:10px 12px;border-bottom:1px solid #e2e8f0;font-size:13px;color:#64748b;">{_escape(r.get("resource", ""))}</td>
          <td style="padding:10px 12px;border-bottom:1px solid #e2e8f0;font-size:13px;color:#64748b;">{prev_title}</td>
          <td style="padding:10px 12px;border-bottom:1px solid #e2e8f0;font-size:13px;color:#1e3a5f;font-weight:500;">{new_title}</td>
          <td style="padding:10px 12px;border-bottom:1px solid #e2e8f0;font-size:12px;font-weight:600;{style}border-radius:4px;white-space:nowrap;">{_escape(result)}</td>
        </tr>"""

    log_url = f"https://github.com/reonzpika/ahuru/blob/main/logs/{_escape(log_filename)}"

    counts = {
        "applied": sum(1 for r in audit_records if r.get("result") == "applied"),
        "error": sum(1 for r in audit_records if r.get("result") == "error"),
        "skipped_mismatch": sum(1 for r in audit_records if r.get("result") == "skipped_mismatch"),
        "dry_run": sum(1 for r in audit_records if r.get("result") in ("dry_run", "dry_run_rollback")),
        "rolled_back": sum(1 for r in audit_records if r.get("result") == "rolled_back"),
    }

    summary_items = []
    if counts["applied"]:
        summary_items.append(f'<span style="color:#166534;font-weight:600;">{counts["applied"]} applied</span>')
    if counts["dry_run"]:
        summary_items.append(f'<span style="color:#0369a1;font-weight:600;">{counts["dry_run"]} dry run</span>')
    if counts["rolled_back"]:
        summary_items.append(f'<span style="color:#6d28d9;font-weight:600;">{counts["rolled_back"]} rolled back</span>')
    if counts["skipped_mismatch"]:
        summary_items.append(f'<span style="color:#854d0e;font-weight:600;">{counts["skipped_mismatch"]} skipped (mismatch)</span>')
    if counts["error"]:
        summary_items.append(f'<span style="color:#991b1b;font-weight:600;">{counts["error"]} error(s)</span>')
    summary_str = " &nbsp;·&nbsp; ".join(summary_items) if summary_items else "No tasks processed"

    th_style = "padding:10px 12px;text-align:left;font-size:12px;color:#64748b;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;border-bottom:2px solid #e2e8f0;"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Āhuru SEO Changes Applied</title>
</head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#1a202c;">
  <div style="max-width:680px;margin:32px auto;background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.1);">

    <div style="background:#1e3a5f;padding:28px 32px;">
      <p style="margin:0;color:#93c5fd;font-size:12px;text-transform:uppercase;letter-spacing:1px;">SEO Apply</p>
      <h1 style="margin:4px 0 0;color:#ffffff;font-size:22px;">Āhuru Candles</h1>
      <p style="margin:6px 0 0;color:#93c5fd;font-size:14px;">{report_date}</p>
    </div>

    <div style="background:#f8fafc;padding:16px 32px;border-bottom:1px solid #e2e8f0;">
      <p style="margin:0;font-size:14px;">{summary_str}</p>
    </div>

    <div style="padding:28px 32px;">
      <table style="width:100%;border-collapse:collapse;margin:0;font-size:14px;">
        <thead>
          <tr style="background:#f1f5f9;">
            <th style="{th_style}">Handle</th>
            <th style="{th_style}">Type</th>
            <th style="{th_style}">Previous Title</th>
            <th style="{th_style}">New Title</th>
            <th style="{th_style}">Result</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>

      <p style="margin:24px 0 0;font-size:13px;color:#64748b;">
        Audit log: <a href="{log_url}" style="color:#1e3a5f;">{_escape(log_filename)}</a>
      </p>
    </div>

    <div style="background:#f1f5f9;padding:16px 32px;border-top:1px solid #e2e8f0;">
      <p style="margin:0;font-size:12px;color:#94a3b8;text-align:center;">
        Generated automatically by the Āhuru SEO pipeline ·
        <a href="https://github.com/reonzpika/ahuru" style="color:#64748b;">View repo</a>
      </p>
    </div>

  </div>
</body>
</html>"""


def send_confirmation_email(audit_records: list) -> None:
    """
    Sends a confirmation email summarising applied SEO changes.
    Subject: Āhuru SEO Changes Applied — DD Month YYYY
    Table: Handle, Resource, Previous Title, New Title, Result.
    Errors and mismatches highlighted in colour.
    Links to audit log on GitHub.

    If RESEND_API_KEY is not set: prints summary to stdout and returns without error (non-fatal).
    """
    report_date = datetime.now(timezone.utc).strftime("%d %B %Y")
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_filename = f"{date_str}-applied.json"
    subject = f"Āhuru SEO Changes Applied — {report_date}"

    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        print("RESEND_API_KEY not set — confirmation email summary:")
        for r in audit_records:
            print(f"  {r.get('handle')} ({r.get('resource')}): {r.get('result')}")
        return

    body_html = _confirmation_email_html(audit_records, report_date, log_filename)

    plain_lines = [f"Āhuru SEO Changes Applied — {report_date}", ""]
    for r in audit_records:
        plain_lines.append(
            f"{r.get('handle')} ({r.get('resource')}): {r.get('result')} | "
            f"{r.get('previous_seo_title', '—')} → {r.get('new_seo_title', '—')}"
        )
    plain_lines.append(f"\nAudit log: https://github.com/reonzpika/ahuru/blob/main/logs/{log_filename}")

    payload = {
        "from": FROM_ADDRESS,
        "to": TO_ADDRESSES,
        "subject": subject,
        "html": body_html,
        "text": "\n".join(plain_lines),
    }

    print(f"  Sending to: {', '.join(TO_ADDRESSES)}")
    print(f"  Subject: {subject}")

    try:
        response = _requests.post(
            RESEND_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        if response.status_code in (200, 201):
            print(f"  ✓ Confirmation email sent — ID: {response.json().get('id', 'unknown')}")
        else:
            print(f"  Warning: Resend API error {response.status_code}: {response.text}")
    except Exception as e:
        print(f"  Warning: Email send failed: {e}")


# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import glob

    reports_dir = os.path.join(os.path.dirname(__file__), "..", "reports")
    report_files = sorted(glob.glob(os.path.join(reports_dir, "2*.md")))

    if not report_files:
        raise FileNotFoundError("No report files found. Run run_weekly.py first.")

    with open(report_files[-1], encoding="utf-8") as f:
        report_text = f.read()

    # Minimal summary for standalone test
    test_summary = {
        "current_7d_clicks": 0,
        "current_7d_impressions": 0,
        "total_clicks_90d": 0,
        "ranked_pages_90d": 0,
        "clicks_wow_pct": None,
        "impressions_wow_pct": None,
    }

    send_report(report_text, test_summary)