"""
shopify_client.py
Shopify Admin GraphQL client for the Āhuru SEO apply pipeline.

Auth model: Client ID + Client Secret → short-lived access token (Jan 2026+).
Credentials read from environment: SHOPIFY_CLIENT_ID, SHOPIFY_CLIENT_SECRET, SHOPIFY_DOMAIN.

Used by apply_changes.py, generate_changes (via baseline_seo), and backfill_previous_seo.py.
"""

import os
import time
from urllib.parse import urlparse

import requests

# ── Token cache ───────────────────────────────────────────────────────────────

_token_cache = {"token": None, "expires_at": 0}


def get_access_token() -> str:
    """
    Returns a valid Shopify Admin API access token.
    Exchanges Client ID + Client Secret for a short-lived token.
    Caches the token in memory; refreshes 60s before expiry.
    """
    if _token_cache["token"] and time.time() < _token_cache["expires_at"] - 60:
        return _token_cache["token"]

    domain = os.environ["SHOPIFY_DOMAIN"]
    resp = requests.post(
        f"https://{domain}/admin/oauth/access_token",
        json={
            "client_id": os.environ["SHOPIFY_CLIENT_ID"],
            "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"],
            "grant_type": "client_credentials",
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = time.time() + data.get("expires_in", 86400)
    return _token_cache["token"]


# ── Base GraphQL call ─────────────────────────────────────────────────────────

def _graphql(query: str, variables: dict = None) -> dict:
    """
    Executes a Shopify Admin GraphQL query or mutation.
    Raises RuntimeError on HTTP errors or GraphQL-level errors.
    """
    domain = os.environ["SHOPIFY_DOMAIN"]
    token = get_access_token()

    resp = requests.post(
        f"https://{domain}/admin/api/2026-01/graphql.json",
        headers={
            "X-Shopify-Access-Token": token,
            "Content-Type": "application/json",
        },
        json={"query": query, "variables": variables or {}},
        timeout=30,
    )
    resp.raise_for_status()
    body = resp.json()

    if "errors" in body:
        raise RuntimeError(f"GraphQL errors: {body['errors']}")

    return body.get("data", {})


# ── Product SEO ───────────────────────────────────────────────────────────────

def get_product_seo(handle: str) -> dict:
    """
    Fetches current SEO fields for a product by handle.
    Returns {"id": "gid://shopify/Product/...", "seo_title": "...", "seo_description": "..."}.
    Raises RuntimeError if not found.
    """
    query = """
    query GetProductSEO($handle: String!) {
      productByHandle(handle: $handle) {
        id
        seo {
          title
          description
        }
      }
    }
    """
    data = _graphql(query, {"handle": handle})
    product = data.get("productByHandle")
    if not product:
        raise RuntimeError(f"Product not found for handle: {handle!r}")

    return {
        "id": product["id"],
        "seo_title": product["seo"]["title"] or "",
        "seo_description": product["seo"]["description"] or "",
    }


def update_product_seo(product_id: str, seo_title: str, seo_description: str) -> dict:
    """
    Updates SEO title and description for a product.
    Raises RuntimeError if userErrors is non-empty.
    Returns the updated product data.
    """
    mutation = """
    mutation UpdateProductSEO($id: ID!, $seo: SEOInput!) {
      productUpdate(input: {id: $id, seo: $seo}) {
        product {
          id
          seo {
            title
            description
          }
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    data = _graphql(mutation, {
        "id": product_id,
        "seo": {"title": seo_title, "description": seo_description},
    })
    result = data.get("productUpdate", {})
    user_errors = result.get("userErrors", [])
    if user_errors:
        raise RuntimeError(f"Shopify userErrors on product update: {user_errors}")

    return result.get("product", {})


# ── Article SEO ───────────────────────────────────────────────────────────────
# Blog articles do not expose `seo` on the Article GraphQL type. Search engine
# listing title and description are stored as `global` metafields `title_tag` and
# `description_tag` (same pattern as the Shopify Admin search listing UI).


def _article_metafields_to_seo(edges: list) -> tuple[str, str]:
    """Maps global title_tag / description_tag metafield edges to seo_title, seo_description."""
    by_key: dict[str, str] = {}
    for edge in edges:
        node = edge.get("node") or {}
        key = node.get("key")
        if key in ("title_tag", "description_tag"):
            by_key[key] = node.get("value") or ""
    return by_key.get("title_tag", ""), by_key.get("description_tag", "")


def _article_seo_metafield_inputs(
    article_id: str,
    seo_title: str,
    seo_description: str,
) -> list[dict]:
    """
    Builds MetafieldInput list for article SEO, using metafield id when the
    field already exists (required by Shopify for updates set in Admin).
    """
    query = """
    query ArticleSeoMetafields($id: ID!) {
      article(id: $id) {
        id
        metafields(first: 20, namespace: "global") {
          edges {
            node {
              id
              key
              namespace
              value
            }
          }
        }
      }
    }
    """
    data = _graphql(query, {"id": article_id})
    article = data.get("article")
    if not article:
        raise RuntimeError(f"Article not found for id: {article_id!r}")

    edges = article.get("metafields", {}).get("edges", [])
    by_key: dict[str, dict] = {}
    for edge in edges:
        node = edge.get("node") or {}
        k = node.get("key")
        if k in ("title_tag", "description_tag"):
            by_key[k] = node

    inputs: list[dict] = []
    for key, new_val in (
        ("title_tag", seo_title),
        ("description_tag", seo_description),
    ):
        existing = by_key.get(key)
        if existing and existing.get("id"):
            inputs.append({"id": existing["id"], "value": new_val})
        else:
            inputs.append({
                "namespace": "global",
                "key": key,
                "value": new_val,
                "type": "single_line_text_field",
            })
    return inputs


def blog_handle_from_shopify_url(url: str) -> str | None:
    """
    Blog handle from storefront URLs such as /blogs/guide/article-handle.
    Returns None if the path is not under /blogs/.
    """
    if not url or not url.strip():
        return None
    parts = [p for p in urlparse(url).path.strip("/").split("/") if p]
    if len(parts) >= 3 and parts[0].lower() == "blogs":
        return parts[1]
    return None


def _article_node_to_seo_dict(node: dict) -> dict:
    edges = node.get("metafields", {}).get("edges", [])
    seo_title, seo_description = _article_metafields_to_seo(edges)
    return {
        "id": node["id"],
        "seo_title": seo_title,
        "seo_description": seo_description,
    }


def get_article_seo(handle: str, blog_handle: str | None = None) -> dict:
    """
    Fetches current SEO fields for a blog article by handle.
    Uses the root Admin `articles` connection with search query handle:... (not limited
    to the first page of each blog). When blog_handle is set (e.g. from shopify_url),
    the match must be in that blog; when omitted, exactly one blog must contain the handle.
    SEO values come from global metafields title_tag and description_tag.
    Raises RuntimeError if not found or ambiguous.
    Returns {"id": "gid://shopify/Article/...", "seo_title": "...", "seo_description": "..."}.
    """
    query = """
    query FindArticleSEO($articleQuery: String!) {
      articles(first: 20, query: $articleQuery) {
        edges {
          node {
            id
            handle
            blog {
              handle
            }
            metafields(first: 20, namespace: "global") {
              edges {
                node {
                  key
                  value
                }
              }
            }
          }
        }
      }
    }
    """
    data = _graphql(query, {"articleQuery": f"handle:{handle}"})
    article_edges = data.get("articles", {}).get("edges", [])

    candidates: list[tuple[str | None, dict]] = []
    for article_edge in article_edges:
        node = article_edge["node"]
        if node.get("handle") != handle:
            continue
        blog_h = (node.get("blog") or {}).get("handle")
        candidates.append((blog_h, node))

    if not candidates:
        raise RuntimeError(
            f"Article not found for handle: {handle!r} (articles search returned no exact match)"
        )

    if blog_handle is not None:
        for bh, node in candidates:
            if bh == blog_handle:
                return _article_node_to_seo_dict(node)
        raise RuntimeError(
            f"Article {handle!r} not found in blog {blog_handle!r} "
            f"(found in: {[c[0] for c in candidates]})"
        )

    if len(candidates) > 1:
        raise RuntimeError(
            f"Ambiguous article handle {handle!r} in blogs {[c[0] for c in candidates]} — "
            "set shopify_url or pass blog_handle"
        )

    return _article_node_to_seo_dict(candidates[0][1])


def update_article_seo(article_id: str, seo_title: str, seo_description: str) -> dict:
    """
    Updates SEO title and description for an article via global metafields.
    Raises RuntimeError if userErrors is non-empty.
    Returns the updated article data.
    """
    metafields = _article_seo_metafield_inputs(article_id, seo_title, seo_description)
    mutation = """
    mutation UpdateArticleSEO($id: ID!, $article: ArticleUpdateInput!) {
      articleUpdate(id: $id, article: $article) {
        article {
          id
          handle
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    data = _graphql(mutation, {
        "id": article_id,
        "article": {"metafields": metafields},
    })
    result = data.get("articleUpdate", {})
    user_errors = result.get("userErrors", [])
    if user_errors:
        raise RuntimeError(f"Shopify userErrors on article update: {user_errors}")

    return result.get("article", {})


# ── Collection SEO ────────────────────────────────────────────────────────────


def get_collection_seo(handle: str) -> dict:
    """
    Fetches current SEO fields for a collection by handle.
    Returns {"id", "seo_title", "seo_description"}.
    """
    query = """
    query GetCollectionSEO($handle: String!) {
      collectionByHandle(handle: $handle) {
        id
        seo {
          title
          description
        }
      }
    }
    """
    data = _graphql(query, {"handle": handle})
    node = data.get("collectionByHandle")
    if not node:
        raise RuntimeError(f"Collection not found for handle: {handle!r}")
    seo = node.get("seo") or {}
    return {
        "id": node["id"],
        "seo_title": (seo.get("title") or "") if seo else "",
        "seo_description": (seo.get("description") or "") if seo else "",
    }


def update_collection_seo(collection_id: str, seo_title: str, seo_description: str) -> dict:
    mutation = """
    mutation UpdateCollectionSEO($input: CollectionInput!) {
      collectionUpdate(input: $input) {
        collection {
          id
          seo {
            title
            description
          }
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    data = _graphql(mutation, {
        "input": {
            "id": collection_id,
            "seo": {"title": seo_title, "description": seo_description},
        },
    })
    result = data.get("collectionUpdate", {})
    user_errors = result.get("userErrors", [])
    if user_errors:
        raise RuntimeError(f"Shopify userErrors on collection update: {user_errors}")
    return result.get("collection", {})


# ── Page SEO ──────────────────────────────────────────────────────────────────
# Admin Page type has no `seo` on PageUpdateInput. Listing title/description use
# `global` metafields `title_tag` and `description_tag` (same pattern as articles).


def _page_seo_metafield_inputs(
    page_id: str,
    seo_title: str,
    seo_description: str,
) -> list[dict]:
    """MetafieldInput list for page SEO (global title_tag / description_tag)."""
    query = """
    query PageSeoMetafields($id: ID!) {
      page(id: $id) {
        id
        metafields(first: 20, namespace: "global") {
          edges {
            node {
              id
              key
              namespace
              value
            }
          }
        }
      }
    }
    """
    data = _graphql(query, {"id": page_id})
    page = data.get("page")
    if not page:
        raise RuntimeError(f"Page not found for id: {page_id!r}")

    edges = page.get("metafields", {}).get("edges", [])
    by_key: dict[str, dict] = {}
    for edge in edges:
        node = edge.get("node") or {}
        k = node.get("key")
        if k in ("title_tag", "description_tag"):
            by_key[k] = node

    inputs: list[dict] = []
    for key, new_val in (
        ("title_tag", seo_title),
        ("description_tag", seo_description),
    ):
        existing = by_key.get(key)
        if existing and existing.get("id"):
            inputs.append({"id": existing["id"], "value": new_val})
        else:
            inputs.append({
                "namespace": "global",
                "key": key,
                "value": new_val,
                "type": "single_line_text_field",
            })
    return inputs


def get_page_seo(handle: str) -> dict:
    """
    Fetches SEO for an online store page by handle (global title_tag / description_tag).
    """
    query = """
    query FindPageSEO($q: String!) {
      pages(first: 5, query: $q) {
        edges {
          node {
            id
            handle
            metafields(first: 20, namespace: "global") {
              edges {
                node {
                  key
                  value
                }
              }
            }
          }
        }
      }
    }
    """
    data = _graphql(query, {"q": f"handle:{handle}"})
    edges = data.get("pages", {}).get("edges", [])
    for edge in edges:
        node = edge.get("node") or {}
        if node.get("handle") != handle:
            continue
        mf_edges = (node.get("metafields") or {}).get("edges", [])
        seo_title, seo_description = _article_metafields_to_seo(mf_edges)
        return {
            "id": node["id"],
            "seo_title": seo_title,
            "seo_description": seo_description,
        }
    raise RuntimeError(f"Page not found for handle: {handle!r}")


def update_page_seo(page_id: str, seo_title: str, seo_description: str) -> dict:
    metafields = _page_seo_metafield_inputs(page_id, seo_title, seo_description)
    mutation = """
    mutation UpdatePageSEO($id: ID!, $page: PageUpdateInput!) {
      pageUpdate(id: $id, page: $page) {
        page {
          id
          handle
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    data = _graphql(mutation, {
        "id": page_id,
        "page": {"metafields": metafields},
    })
    result = data.get("pageUpdate", {})
    user_errors = result.get("userErrors", [])
    if user_errors:
        raise RuntimeError(f"Shopify userErrors on page update: {user_errors}")
    return result.get("page", {})


# ── Routers ───────────────────────────────────────────────────────────────────

def get_seo(resource: str, handle: str, blog_handle: str | None = None) -> dict:
    """Routes by resource type to the matching Shopify SEO reader."""
    if resource == "product":
        return get_product_seo(handle)
    if resource == "article":
        return get_article_seo(handle, blog_handle=blog_handle)
    if resource == "collection":
        return get_collection_seo(handle)
    if resource == "page":
        return get_page_seo(handle)
    raise ValueError(
        f"Unknown resource type: {resource!r}. "
        f"Expected 'product', 'article', 'collection', or 'page'."
    )


def update_seo(
    resource: str,
    resource_id: str,
    seo_title: str,
    seo_description: str,
) -> dict:
    """Routes by resource type to the matching Shopify SEO writer."""
    if resource == "product":
        return update_product_seo(resource_id, seo_title, seo_description)
    if resource == "article":
        return update_article_seo(resource_id, seo_title, seo_description)
    if resource == "collection":
        return update_collection_seo(resource_id, seo_title, seo_description)
    if resource == "page":
        return update_page_seo(resource_id, seo_title, seo_description)
    raise ValueError(
        f"Unknown resource type: {resource!r}. "
        f"Expected 'product', 'article', 'collection', or 'page'."
    )


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    print("Testing shopify_client.py")
    print("=" * 60)

    print("\nProduct SEO — meri-kirihimete-christmas-card:")
    print("-" * 40)
    try:
        result = get_product_seo("meri-kirihimete-christmas-card")
        print(f"  ID:               {result['id']}")
        print(f"  SEO title:        {result['seo_title']!r}")
        print(f"  SEO description:  {result['seo_description']!r}")
        print("  ✓ Product lookup OK")
    except Exception as e:
        print(f"  ✗ Error: {e}")

    print("\nArticle SEO — best-essential-oils-for-diffusers-guide:")
    print("-" * 40)
    try:
        result = get_article_seo("best-essential-oils-for-diffusers-guide")
        print(f"  ID:               {result['id']}")
        print(f"  SEO title:        {result['seo_title']!r}")
        print(f"  SEO description:  {result['seo_description']!r}")
        print("  ✓ Article lookup OK")
    except Exception as e:
        print(f"  ✗ Error: {e}")

    print("\nCollection SEO (replace handle in script if needed):")
    print("-" * 40)
    try:
        result = get_collection_seo("all")
        print(f"  ID:               {result['id']}")
        print(f"  SEO title:        {result['seo_title']!r}")
        print(f"  SEO description:  {result['seo_description']!r}")
        print("  ✓ Collection lookup OK")
    except Exception as e:
        print(f"  ✗ Error: {e}")

    print("\nPage SEO (replace handle if needed):")
    print("-" * 40)
    try:
        result = get_page_seo("contact")
        print(f"  ID:               {result['id']}")
        print(f"  SEO title:        {result['seo_title']!r}")
        print(f"  SEO description:  {result['seo_description']!r}")
        print("  ✓ Page lookup OK")
    except Exception as e:
        print(f"  ✗ Error: {e}")
