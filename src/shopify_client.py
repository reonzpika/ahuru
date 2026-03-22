"""
shopify_client.py
Shopify Admin GraphQL client for the Āhuru SEO apply pipeline.

Auth model: Client ID + Client Secret → short-lived access token (Jan 2026+).
Credentials read from environment: SHOPIFY_CLIENT_ID, SHOPIFY_CLIENT_SECRET, SHOPIFY_DOMAIN.

Used exclusively by apply_changes.py — do not call from other pipeline modules.
"""

import os
import time

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


def get_article_seo(handle: str) -> dict:
    """
    Fetches current SEO fields for a blog article by handle.
    Searches across all blogs (up to 20) and all articles (up to 100 per blog).
    Uses exact handle matching — does not rely on fuzzy query filter.
    SEO values come from global metafields title_tag and description_tag.
    Raises RuntimeError if not found.
    Returns {"id": "gid://shopify/Article/...", "seo_title": "...", "seo_description": "..."}.
    """
    query = """
    query GetBlogsAndArticles {
      blogs(first: 20) {
        edges {
          node {
            handle
            articles(first: 100) {
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
        }
      }
    }
    """
    data = _graphql(query)
    blogs = data.get("blogs", {}).get("edges", [])

    for blog_edge in blogs:
        articles = blog_edge["node"].get("articles", {}).get("edges", [])
        for article_edge in articles:
            node = article_edge["node"]
            if node["handle"] == handle:
                edges = node.get("metafields", {}).get("edges", [])
                seo_title, seo_description = _article_metafields_to_seo(edges)
                return {
                    "id": node["id"],
                    "seo_title": seo_title,
                    "seo_description": seo_description,
                }

    raise RuntimeError(
        f"Article not found for handle: {handle!r} "
        f"(searched {len(blogs)} blogs)"
    )


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


# ── Routers ───────────────────────────────────────────────────────────────────

def get_seo(resource: str, handle: str) -> dict:
    """Routes to get_product_seo or get_article_seo based on resource type."""
    if resource == "product":
        return get_product_seo(handle)
    elif resource == "article":
        return get_article_seo(handle)
    else:
        raise ValueError(f"Unknown resource type: {resource!r}. Expected 'product' or 'article'.")


def update_seo(
    resource: str,
    resource_id: str,
    seo_title: str,
    seo_description: str,
) -> dict:
    """Routes to update_product_seo or update_article_seo based on resource type."""
    if resource == "product":
        return update_product_seo(resource_id, seo_title, seo_description)
    elif resource == "article":
        return update_article_seo(resource_id, seo_title, seo_description)
    else:
        raise ValueError(f"Unknown resource type: {resource!r}. Expected 'product' or 'article'.")


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
