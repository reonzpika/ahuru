"""
report_monthly.py
Generates the monthly strategic SEO report via Claude API.

Mirrors report.py structure but uses:
  - system_prompt_monthly.md (strategic framing, not tactical)
  - Higher MAX_TOKENS (monthly report is longer)
  - Saves to reports/monthly/YYYY-MM.md
"""

import json
import os
from datetime import datetime, timezone

import anthropic


# ── Configuration ─────────────────────────────────────────────────────────────

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 6000   # Monthly report is longer than weekly

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "prompts")
REPORTS_DIR = os.path.join(os.path.dirname(__file__), "..", "reports", "monthly")


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_system_prompt():
    path = os.path.join(PROMPTS_DIR, "system_prompt_monthly.md")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def build_user_message(analysis):
    report_month = datetime.now(timezone.utc).strftime("%B %Y")

    return f"""Please generate the monthly SEO report for Āhuru.

Report month: {report_month}

## Monthly GSC Analysis Data

```json
{json.dumps(analysis, indent=2)}
```

Follow the report format in your instructions exactly.
Where YoY data is unavailable (data_available: false), note this clearly and skip the comparison tables — do not invent numbers.
Every strategic recommendation must be grounded in the data above.
"""


# ── Core function ─────────────────────────────────────────────────────────────

def generate_monthly_report(analysis):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY environment variable is not set.")

    client = anthropic.Anthropic(api_key=api_key)
    system_prompt = load_system_prompt()
    user_message = build_user_message(analysis)

    print(f"Sending to Claude API (model: {MODEL})...")
    print(f"Analysis data size: ~{len(json.dumps(analysis)) // 1024}KB")

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    report_text = response.content[0].text

    print(f"Report generated — {len(report_text)} chars")
    print(f"Input tokens:  {response.usage.input_tokens}")
    print(f"Output tokens: {response.usage.output_tokens}")

    return report_text


# ── Save ──────────────────────────────────────────────────────────────────────

def save_monthly_report(report_text):
    """
    Saves to reports/monthly/YYYY-MM.md
    Also writes reports/monthly/latest.md
    """
    os.makedirs(REPORTS_DIR, exist_ok=True)

    month_str = datetime.utcnow().strftime("%Y-%m")
    dated_path = os.path.join(REPORTS_DIR, f"{month_str}.md")
    latest_path = os.path.join(REPORTS_DIR, "latest.md")

    with open(dated_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    with open(latest_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    print(f"Saved: {dated_path}")
    print(f"Updated: {latest_path}")

    return dated_path
