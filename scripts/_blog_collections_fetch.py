"""One-off: fetch collection data for blog HTML. Run from repo root."""
import json
import os
import sys
from pathlib import Path

repo = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo))
for line in (repo / ".env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from src.shopify_client import _graphql  # noqa: E402


def main() -> None:
    terms = ["self-care", "best seller", "wellness", "essential oil candle", "bestseller"]
    for term in terms:
        data = _graphql(
            """
            query ($q: String!) {
              collections(first: 20, query: $q) {
                edges { node { handle title } }
              }
            }
            """,
            {"q": term},
        )
        print("---", term)
        for e in data.get("collections", {}).get("edges", []):
            n = e["node"]
            print(" ", n["handle"], "|", n["title"][:70])

    handles = [
        "essential-oils-for-diffuser",
        "essential-oil-diffuser",
        "diffuser-oil-nz",
        "relaxation-sleep",
        "scented-candles-nz",
    ]
    parts = [
        f'{h.replace("-", "_")}: collectionByHandle(handle: "{h}") '
        "{ id handle title descriptionHtml image { url altText } }"
        for h in handles
    ]
    q = "query { " + " ".join(parts) + " }"
    full = _graphql(q)
    print(json.dumps(full, indent=2))


def probe_handles(handles: list[str]) -> None:
    for h in handles:
        r = _graphql(
            'query($h: String!) { c: collectionByHandle(handle: $h) { handle title image { url } } }',
            {"h": h},
        )
        c = r.get("c")
        print(h, "->", c["handle"] if c else None, (c or {}).get("title", ""))


def search_collections(term: str) -> None:
    data = _graphql(
        """
        query ($q: String!) {
          collections(first: 15, query: $q) {
            edges { node { handle title } }
          }
        }
        """,
        {"q": term},
    )
    print("---", term)
    for e in data.get("collections", {}).get("edges", []):
        n = e["node"]
        print(" ", n["handle"], "|", n["title"][:55])


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "search":
        for t in sys.argv[2:]:
            search_collections(t)
    else:
        main()
        print("--- probe")
        probe_handles(
            [
                "essential-oil-diffuser-nz",
                "essential-oil-diffuser",
                "relaxation-sleep",
                "jewellery-best-sellers",
            ]
        )
