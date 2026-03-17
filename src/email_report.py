"""
email_report.py
Converts the Markdown SEO report to a clean HTML email and sends via Resend.

From:    ahuru-seo-report@clinicpro.co.nz
To:      info@ahurucandles.com, ryo@clinicpro.co.nz
Trigger: called from run_weekly.py after save_report()
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


# ── HTML wrapper ──────────────────────────────────────────────────────────────

def wrap_html(body_html, report_date, summary):
    """Wraps the report body in a full HTML email template."""

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
  <title>Āhuru SEO Report — {report_date}</title>
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

    <!-- Report body -->
    <div style="padding:28px 32px;">
      {body_html}
    </div>

    <!-- Footer -->
    <div style="background:#f1f5f9;padding:16px 32px;border-top:1px solid #e2e8f0;">
      <p style="margin:0;font-size:12px;color:#94a3b8;text-align:center;">
        Generated automatically by the Āhuru SEO pipeline · 
        <a href="https://github.com/reonzpika/ahuru" style="color:#64748b;">View repo</a>
      </p>
    </div>

  </div>
</body>
</html>"""


# ── Send via Resend ───────────────────────────────────────────────────────────

def send_report(report_text, summary):
    """
    Converts Markdown report to HTML and sends via Resend API.
    Uses only stdlib (urllib) — no extra dependencies.

    Args:
        report_text: Full Markdown string of the report
        summary:     Dict from analyse() with click/impression stats
    """
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        raise EnvironmentError("RESEND_API_KEY environment variable is not set.")

    report_date = datetime.now(timezone.utc).strftime("%d %B %Y")

    print("Converting Markdown to HTML...")
    body_html = markdown_to_html(report_text)
    full_html = wrap_html(body_html, report_date, summary)

    # Plain text fallback — strip Markdown for email clients that prefer it
    plain_text = re.sub(r"[#*`]", "", report_text)
    plain_text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", plain_text)

    report_type = summary.get("_report_type", "weekly")
    report_month = summary.get("_report_month", "")
    if report_type == "monthly":
        subject = f"Āhuru SEO Monthly Report — {report_month}"
    else:
        subject = f"Āhuru SEO Weekly Report — {report_date}"

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
        print(f"✓ Email sent — ID: {result.get('id', 'unknown')}")
        return result
    else:
        raise RuntimeError(f"Resend API error {response.status_code}: {response.text}")


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
