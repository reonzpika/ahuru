import json
import os
import re
import sys
from pathlib import Path

repo = Path(__file__).resolve().parents[1]
for line in (repo / ".env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())
sys.path.insert(0, str(repo))
from src.shopify_client import _graphql  # noqa: E402

HANDLES = ["essential-oils-for-diffuser", "essential-oil-diffuser-nz"]


def strip_html(html: str, max_len: int = 140) -> str:
    if not html:
        return ""
    t = re.sub(r"<[^>]+>", " ", html)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:max_len] + ("…" if len(t) > max_len else "")


def main() -> None:
    parts = []
    for i, h in enumerate(HANDLES):
        parts.append(
            f"""
            c{i}: collectionByHandle(handle: "{h}") {{
              handle
              title
              descriptionHtml
              image {{ url altText }}
            }}
            """
        )
    data = _graphql("query { " + " ".join(parts) + " }")
    base = "https://www.ahurucandles.co.nz"
    for i, h in enumerate(HANDLES):
        c = data.get(f"c{i}")
        if not c:
            print("MISSING", h)
            continue
        print(json.dumps({**c, "url": f"{base}/collections/{c['handle']}", "snippet": strip_html(c.get("descriptionHtml") or "")}, indent=2))


if __name__ == "__main__":
    main()
