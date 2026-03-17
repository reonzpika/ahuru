"""
report.py
Sends the structured GSC analysis to Claude API and saves the weekly report.

The system prompt provides full Āhuru brand context.
The analysis data is sent as structured JSON.
Output is a Markdown report saved to /reports/YYYY-MM-DD.md
"""

import json
import os
from datetime import datetime, timezone

import anthropic


# ── Configuration ─────────────────────────────────────────────────────────────

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 4096

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "prompts")
REPORTS_DIR = os.path.join(os.path.dirname(__file__), "..", "reports")


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_system_prompt():
    path = os.path.join(PROMPTS_DIR, "system_prompt.md")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def build_user_message(analysis):
    """
    Formats the analysis data into a clear prompt.
    We inject the current date so the report header is accurate.
    """
    # NZ date (UTC+12 standard, UTC+13 daylight — use UTC+12 as safe default)
    report_date = datetime.now(timezone.utc).strftime("%d %B %Y")

    return f"""Please generate the weekly SEO report for Āhuru.

Report date: {report_date}

## GSC Analysis Data

```json
{json.dumps(analysis, indent=2)}
```

Follow the report format in your instructions exactly.
Every recommendation must reference specific URLs from the data above.
Write all meta titles and descriptions as ready-to-paste strings.
"""


# ── Core function ─────────────────────────────────────────────────────────────

def generate_report(analysis):
    """
    Send analysis to Claude API and return the report as a string.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY environment variable is not set."
        )

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

def save_report(report_text):
    """
    Save the report to /reports/YYYY-MM-DD.md
    Also overwrites /reports/latest.md for easy access.
    Returns the dated filepath.
    """
    os.makedirs(REPORTS_DIR, exist_ok=True)

    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    dated_path = os.path.join(REPORTS_DIR, f"{date_str}.md")
    latest_path = os.path.join(REPORTS_DIR, "latest.md")

    with open(dated_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    with open(latest_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    print(f"Saved: {dated_path}")
    print(f"Updated: {latest_path}")

    return dated_path


# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import glob
    import sys

    sys.path.insert(0, os.path.dirname(__file__))
    from analyse import analyse

    # Find the most recent data file
    data_files = sorted(
        glob.glob(os.path.join(os.path.dirname(__file__), "..", "data", "gsc_*.json"))
    )
    if not data_files:
        raise FileNotFoundError(
            "No GSC data files found in /data/. Run gsc_fetch.py first."
        )

    latest_data = data_files[-1]
    print(f"Loading data: {latest_data}")

    with open(latest_data) as f:
        raw_data = json.load(f)

    analysis = analyse(raw_data)
    report = generate_report(analysis)
    save_report(report)
