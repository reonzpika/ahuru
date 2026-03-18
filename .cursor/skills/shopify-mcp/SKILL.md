---
name: shopify-mcp
description: Use the Shopify MCP tools to read or write data on the Āhuru Shopify store (ahurucandles.myshopify.com). Trigger when the user asks about products, SEO titles, meta descriptions, blog articles, collections, orders, customers, or navigation. Also trigger when cross-referencing SEO report findings against live store data, or applying changes from the weekly/monthly SEO report. Always prefer Shopify MCP over web fetch or public .json endpoints.
---

# Shopify MCP — Āhuru Store

Store: `ahurucandles.myshopify.com`
API version: `2026-01`
Auth: Client credentials (auto-handled by MCP — no token management needed)

---

## Available Tools

| Tool | Purpose |
|------|---------|
| `get-products` | List products, optional title search and limit |
| `get-product-by-id` | Fetch full product including SEO fields |
| `update-product` | Update title, description, handle, SEO, tags, status, metafields |
| `create-product` | Create new product with SEO fields |
| `delete-product` | Delete product by GID |
| `manage-product-variants` | Create or update variants |
| `manage-product-options` | Create, update, delete product options |
| `delete-product-variants` | Delete specific variants |
| `get-orders` | List orders with status filter |
| `get-order-by-id` | Fetch single order |
| `update-order` | Update order tags, notes, metafields |
| `get-customers` | List customers with search |
| `get-customer-orders` | Orders for a specific customer |
| `update-customer` | Update customer fields and metafields |

---

## SEO Fields

### Reading

Always use `get-product-by-id` — `get-products` does not return SEO fields.

```
get-product-by-id
  productId: "gid://shopify/Product/NUMERIC_ID"
```

Returns:
```json
{
  "product": {
    "id": "gid://shopify/Product/...",
    "title": "...",
    "handle": "...",
    "seo": {
      "title": "meta title here",
      "description": "meta description here"
    }
  }
}
```

### Writing

Use `update-product` with the `seo` object:

```
update-product
  id: "gid://shopify/Product/NUMERIC_ID"
  seo:
    title: "New SEO title (max 60 chars)"
    description: "New meta description (max 155 chars)"
```

Always fetch current values before updating so you can show before/after.

---

## Standard Workflow for SEO Updates

```
1. get-products searchTitle:"product name" limit:5
   → get the GID

2. get-product-by-id productId:"gid://shopify/Product/XXXXXXX"
   → confirm current seo.title and seo.description

3. Show before/after to user and wait for approval

4. update-product id:"gid://shopify/Product/XXXXXXX"
   seo:{title:"...", description:"..."}

5. Confirm applied — show updated values
```

---

## Human Approval Rule — Non-Negotiable

Never call any write tool without explicit human confirmation.

Before any `update-product`, `create-product`, `update-order`, or `update-customer` call:

1. Show the proposed change:
```
Proposed change:
  Product: Sterling Silver Balance Fidget Ring
  Field: SEO title
  Before: "Discover the Perfect Balance with our Sterling Silver Fidget Ring"
  After:  "Sterling Silver Balance Fidget Ring — NZ Anxiety Jewellery"

Apply this change? (yes/no)
```
2. Wait for explicit approval ("yes", "apply it", "go ahead")
3. Call the write tool
4. Show updated values to confirm

---

## Known Limitations

- **Blog articles and pages**: No dedicated MCP tools. For blog article SEO updates, use `shopify_client.py` in the repo for direct GraphQL calls.
- **SEO patch note**: `getProductById.js` in the global npm package was manually patched to return `seo { title description }`. If `shopify-mcp` is updated via `npm install -g shopify-mcp`, the patch is overwritten. To reapply, edit `C:\Users\reonz\AppData\Roaming\npm\node_modules\shopify-mcp\dist\tools\getProductById.js` — add `seo { title description }` to the GraphQL query and `seo: { title: product.seo.title, description: product.seo.description }` to the formatted output.
- **MCP reconnect**: If the MCP stops after a Cursor restart, go to Settings → Tools & Integrations → MCP → disable and re-enable the shopify server.

---

## Automated Pipeline Boundary

This skill covers interactive, human-in-the-loop operations in Cursor only.

The automated pipeline (`shopify_client.py`, `apply_changes.py`) uses direct Python GraphQL calls — not the MCP. Automated changes always require human approval via the `apply_changes.yml` GitHub Actions workflow (manual trigger only).