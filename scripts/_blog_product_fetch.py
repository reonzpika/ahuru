"""Fetch product GIDs, numeric IDs, first variant for blog embed."""
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

HANDLES = [
    "best-seller-essential-oil-blends-bundle",
    "happy-essential-oil-blend",
    "emotional-rescue-essential-oil-blend",
    "anxiety-essential-oil",
    "rose-geranium-essential-oil",
    "relax-essential-oil-blend",
    "womens-essential-oil-blend",
    "lift-me-up-essential-oil-blend",
]


def numeric_id(gid: str) -> str:
    return gid.rsplit("/", 1)[-1]


def main() -> None:
    parts = []
    for i, h in enumerate(HANDLES):
        parts.append(
            f"""
            p{i}: productByHandle(handle: "{h}") {{
              id
              legacyResourceId
              handle
              title
              variants(first: 25) {{
                edges {{
                  node {{
                    id
                    legacyResourceId
                    title
                    availableForSale
                  }}
                }}
              }}
            }}
            """
        )
    q = "query { " + " ".join(parts) + " }"
    data = _graphql(q)
    out = {}
    for i, h in enumerate(HANDLES):
        node = data.get(f"p{i}")
        if not node:
            out[h] = None
            continue
        edges = node.get("variants", {}).get("edges", [])
        variants = [e["node"] for e in edges]
        first = variants[0] if variants else None
        multi = len(variants) > 1
        out[h] = {
            "product_gid": node["id"],
            "product_numeric": node.get("legacyResourceId") or numeric_id(node["id"]),
            "handle": node["handle"],
            "title": node["title"],
            "multi_variant": multi,
            "variant_count": len(variants),
            "first_variant_numeric": (first.get("legacyResourceId") or numeric_id(first["id"])) if first else None,
            "first_available": first.get("availableForSale") if first else None,
        }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
