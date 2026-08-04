import os
import sys
from pathlib import Path

repo = Path(__file__).resolve().parents[1]
for line in (repo / ".env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())
sys.path.insert(0, str(repo))
from src.shopify_client import _graphql

for h in sys.argv[1:]:
    r = _graphql(
        "query($h: String!) { c: collectionByHandle(handle: $h) { handle title image { url } } }",
        {"h": h},
    )
    c = r.get("c")
    print(h, "OK" if c else "MISSING", (c or {}).get("title", ""))
