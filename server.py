#!/usr/bin/env python3
"""
ConnectWise Sell MCP Server
FastMCP HTTP server wrapping the ConnectWise Sell (Quosal) REST API.
Covers Quotes, Quote Items, Tabs, Customers, Terms, Templates, and Recurring Revenue.
"""

import os
import base64
import json
import time
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.auth import AccessToken, TokenVerifier
from starlette.requests import Request as StarletteRequest
from starlette.responses import JSONResponse

for env_path in (
    Path(__file__).resolve().parent / ".env",
    Path(__file__).resolve().parent.parent / ".env",
):
    if env_path.exists():
        load_dotenv(env_path)
        break

# ── Sell API client ────────────────────────────────────────────────────────────

SELL_BASE = os.environ.get("SELL_BASE_URL", "https://sellapi.quosalsell.com")
_raw_auth = (
    f"{os.environ['SELL_ACCESS_KEY']}+{os.environ['SELL_USERNAME']}"
    f":{os.environ['SELL_PASSWORD']}"
)
SELL_AUTH = base64.b64encode(_raw_auth.encode()).decode()
SELL_HEADERS = {
    "Authorization": f"basic {SELL_AUTH}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}
PAGE_SIZE = 100


def sell_get(path: str, params: Optional[dict] = None) -> list | dict:
    url = SELL_BASE + path
    if params:
        url += "?" + urlencode(params)
    req = Request(url, headers=SELL_HEADERS)
    for attempt in range(3):
        try:
            resp = urlopen(req, timeout=30)
            return json.loads(resp.read())
        except HTTPError as e:
            if e.code == 429:
                time.sleep(2 ** attempt)
            else:
                return []
    return []


def sell_post(path: str, body: Optional[dict] = None) -> dict:
    data = json.dumps(body or {}).encode()
    req = Request(SELL_BASE + path, data=data, headers=SELL_HEADERS, method="POST")
    resp = urlopen(req, timeout=30)
    return json.loads(resp.read())


def sell_patch(path: str, operations: list) -> dict:
    data = json.dumps(operations).encode()
    req = Request(SELL_BASE + path, data=data, headers=SELL_HEADERS, method="PATCH")
    resp = urlopen(req, timeout=30)
    return json.loads(resp.read())


def sell_paginate(path: str, conditions: Optional[str] = None, extra: Optional[dict] = None) -> list:
    results = []
    page = 1
    while True:
        params: dict = {"pageSize": PAGE_SIZE, "page": page}
        if conditions:
            params["conditions"] = conditions
        if extra:
            params.update(extra)
        data = sell_get(path, params)
        if not data or not isinstance(data, list):
            break
        results.extend(data)
        if len(data) < PAGE_SIZE:
            break
        page += 1
    return results


# ── Helpers ───────────────────────────────────────────────────────────────────

def _trunc(text: str, max_chars: int = 200) -> str:
    text = (text or "").strip()
    return text[:max_chars] + "..." if len(text) > max_chars else text


def _date(val) -> str:
    if not val:
        return "—"
    return str(val)[:10]


def _dollar(val) -> str:
    try:
        return f"${float(val):,.2f}"
    except (TypeError, ValueError):
        return "—"


def _pagination_footer(total: int, limit: int, offset: int = 0) -> str:
    shown_end = offset + limit
    if total <= shown_end:
        return ""
    return f"\n\n_Showing {offset + 1}–{min(shown_end, total)} of {total}. Pass offset={shown_end} for next page._"


def _safe_str(value: str, max_len: int = 100) -> str:
    if not value:
        return ""
    sanitized = "".join(c for c in value if c not in ('"', "'", "(", ")", "[", "]"))
    return sanitized[:max_len].strip()


class _StaticTokenVerifier(TokenVerifier):
    def __init__(self, token: str):
        super().__init__()
        self._token = token

    async def verify_token(self, token: str) -> "AccessToken | None":
        if token == self._token:
            return AccessToken(token=token, client_id="mcp-client", scopes=[])
        return None


_mcp_auth_token = os.environ.get("MCP_AUTH_TOKEN")
_mcp_auth = _StaticTokenVerifier(_mcp_auth_token) if _mcp_auth_token else None

mcp = FastMCP("cw-sell", auth=_mcp_auth)


# ══════════════════════════════════════════════════════════════════════════════
# QUOTES
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def list_quotes(
    account_name: str = "",
    status: str = "",
    rep: str = "",
    is_accepted: str = "",
    is_sent: str = "",
    close_date_from: str = "",
    close_date_to: str = "",
    limit: int = 25,
    offset: int = 0,
) -> str:
    """
    List ConnectWise Sell quotes with optional filters.

    Args:
        account_name: Filter by account/company name (partial match)
        status: Quote status (e.g. "Open", "Won", "Lost")
        rep: Primary rep name or username (partial match)
        is_accepted: Filter by acceptance: "true" or "false"
        is_sent: Filter by sent status: "true" or "false"
        close_date_from: Expected close date from YYYY-MM-DD
        close_date_to: Expected close date to YYYY-MM-DD
        limit: Max results per page (default 25)
        offset: Pagination offset
    """
    parts = []
    if account_name:
        parts.append(f'accountName contains "{_safe_str(account_name)}"')
    if status:
        parts.append(f'quoteStatus eq "{_safe_str(status)}"')
    if rep:
        parts.append(f'primaryRep contains "{_safe_str(rep)}"')
    if is_accepted in ("true", "false"):
        parts.append(f"isAccepted eq {is_accepted}")
    if is_sent in ("true", "false"):
        parts.append(f"isSent eq {is_sent}")
    if close_date_from:
        parts.append(f'expectedCloseDate ge "{_safe_str(close_date_from, 10)}"')
    if close_date_to:
        parts.append(f'expectedCloseDate le "{_safe_str(close_date_to, 10)}"')

    conditions = " and ".join(parts) or None
    fields = "id,name,quoteNumber,quoteVersion,accountName,quoteStatus,quoteTotal,recurringTotal,isAccepted,isSent,primaryRep,expectedCloseDate,expirationDate,probability"

    all_results = sell_paginate("/api/quotes", conditions=conditions, extra={"includeFields": fields})
    total = len(all_results)
    page = all_results[offset: offset + limit]

    if not page:
        return "No quotes found."

    out = [
        f"Found {total} quote(s):",
        "",
        "| # | Name | Account | Status | Total | Recurring | Accepted | Rep | Close |",
        "|---|------|---------|--------|-------|-----------|----------|-----|-------|",
    ]
    for q in page:
        out.append(
            f"| {q.get('quoteNumber', '—')}v{q.get('quoteVersion', '?')} "
            f"| {_trunc(q.get('name', ''), 35)} "
            f"| {_trunc(q.get('accountName', '—'), 25)} "
            f"| {q.get('quoteStatus', '—')} "
            f"| {_dollar(q.get('quoteTotal'))} "
            f"| {_dollar(q.get('recurringTotal'))} "
            f"| {'Yes' if q.get('isAccepted') else 'No'} "
            f"| {_trunc(q.get('primaryRep', '—'), 15)} "
            f"| {_date(q.get('expectedCloseDate'))} |"
        )

    out.append(_pagination_footer(total, limit, offset))
    return "\n".join(out)


@mcp.tool()
def get_quote(quote_id: str) -> str:
    """
    Get full detail for a single quote by its ID.

    Args:
        quote_id: The Sell quote ID (use list_quotes to find IDs)
    """
    quote = sell_get(f"/api/quotes/{quote_id}")
    if not quote or isinstance(quote, list):
        return f"Quote {quote_id} not found."

    lines = [
        f"# Quote {quote.get('quoteNumber', quote_id)}v{quote.get('quoteVersion', '?')} — {quote.get('name', '—')}",
        "",
        f"**Account:** {quote.get('accountName', '—')}",
        f"**Status:** {quote.get('quoteStatus', '—')}",
        f"**Primary Rep:** {quote.get('primaryRep', '—')}",
        f"**Accepted:** {'Yes' if quote.get('isAccepted') else 'No'} | **Sent:** {'Yes' if quote.get('isSent') else 'No'}",
        f"**Probability:** {quote.get('probability', '—')}%",
        f"**Expected Close:** {_date(quote.get('expectedCloseDate'))}",
        f"**Expiration:** {_date(quote.get('expirationDate'))}",
        "",
        f"**Quote Total:** {_dollar(quote.get('quoteTotal'))}",
        f"**Recurring Total:** {_dollar(quote.get('recurringTotal'))}",
        f"**Subtotal:** {_dollar(quote.get('subtotal'))}",
        f"**Tax:** {_dollar(quote.get('tax'))}",
    ]

    if quote.get('shortDescription'):
        lines.extend(["", f"**Description:** {_trunc(quote['shortDescription'], 300)}"])
    if quote.get('quoteNotes'):
        lines.extend(["", f"**Notes:** {_trunc(quote['quoteNotes'], 300)}"])

    return "\n".join(lines)


@mcp.tool()
def get_quote_versions(quote_number: str) -> str:
    """
    List all versions of a quote by quote number.

    Args:
        quote_number: The quote number (not the ID — the human-readable quote #)
    """
    versions = sell_get(f"/api/quotes/{quote_number}/versions")
    if not versions or not isinstance(versions, list):
        return f"No versions found for quote {quote_number}."

    out = [f"Found {len(versions)} version(s) of quote {quote_number}:", "", "| Version | Status | Total | Recurring | Accepted | Modified |"]
    out.append("|---------|--------|-------|-----------|----------|----------|")
    for v in versions:
        out.append(
            f"| v{v.get('quoteVersion', '?')} "
            f"| {v.get('quoteStatus', '—')} "
            f"| {_dollar(v.get('quoteTotal'))} "
            f"| {_dollar(v.get('recurringTotal'))} "
            f"| {'Yes' if v.get('isAccepted') else 'No'} "
            f"| {_date(v.get('modifyDate'))} |"
        )

    return "\n".join(out)


@mcp.tool()
def copy_quote(source_quote_id: str) -> str:
    """
    Create a new quote by copying an existing quote or template.

    This is the only way to create a quote in Sell — new quotes must start
    from a copy of an existing quote or a template.

    Use get_templates to browse available templates, then pass the template's
    quote ID as source_quote_id.

    Args:
        source_quote_id: ID of the quote or template to copy from
    """
    try:
        result = sell_post(f"/api/quotes/copyById/{source_quote_id}")
        new_id = result.get("id", "?")
        new_num = result.get("quoteNumber", "?")
        name = result.get("name", "—")
        return f"Quote created from copy — ID: {new_id} | Number: {new_num} | Name: {name}"
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("Failed to copy quote %s: %s", source_quote_id, e, exc_info=True)
        return "Failed to copy quote. Check server logs for details."


@mcp.tool()
def update_quote(
    quote_id: str,
    status: str = "",
    expiration_date: str = "",
    expected_close_date: str = "",
    probability: int = -1,
    short_description: str = "",
    quote_notes: str = "",
) -> str:
    """
    Update fields on an existing quote.

    Only include fields you want to change — unset fields are ignored.

    Args:
        quote_id: The Sell quote ID
        status: New quote status (e.g. "Won", "Lost", "Open")
        expiration_date: New expiration date YYYY-MM-DD
        expected_close_date: New expected close date YYYY-MM-DD
        probability: Close probability 0–100 (-1 = leave unchanged)
        short_description: Quote description
        quote_notes: Internal notes
    """
    operations = []
    if status:
        operations.append({"op": "replace", "path": "/quoteStatus", "value": status})
    if expiration_date:
        operations.append({"op": "replace", "path": "/expirationDate", "value": expiration_date})
    if expected_close_date:
        operations.append({"op": "replace", "path": "/expectedCloseDate", "value": expected_close_date})
    if probability >= 0:
        operations.append({"op": "replace", "path": "/probability", "value": probability})
    if short_description:
        operations.append({"op": "replace", "path": "/shortDescription", "value": short_description})
    if quote_notes:
        operations.append({"op": "replace", "path": "/quoteNotes", "value": quote_notes})

    if not operations:
        return "No fields specified to update."

    try:
        result = sell_patch(f"/api/quotes/{quote_id}", operations)
        name = result.get("name", "—")
        new_status = result.get("quoteStatus", "—")
        return f"Quote {quote_id} updated — {name} | Status: {new_status}"
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("Failed to update quote %s: %s", quote_id, e, exc_info=True)
        return "Failed to update quote. Check server logs for details."


# ══════════════════════════════════════════════════════════════════════════════
# QUOTE ITEMS, TABS, CUSTOMERS, TERMS
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_quote_items(
    quote_id: str,
    include_optional: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> str:
    """
    List line items on a quote.

    Args:
        quote_id: The Sell quote ID
        include_optional: Include optional (unselected) items (default True)
        limit: Max results per page
        offset: Pagination offset
    """
    conditions = f'idQuote eq "{quote_id}"'
    if not include_optional:
        conditions += " and isOptional eq false"

    fields = "id,idQuote,shortDescription,quantity,quoteItemPrice,recurringAmount,extendedPrice,recurringTotal,isOptional,isSold,productType,manufacturerPartNumber,uom,period"
    all_results = sell_paginate("/api/quoteItems", conditions=conditions, extra={"includeFields": fields})
    total = len(all_results)
    page = all_results[offset: offset + limit]

    if not page:
        return f"No items found for quote {quote_id}."

    quote_total = sum(float(i.get("extendedPrice") or 0) for i in all_results if not i.get("isOptional"))
    recurring_total = sum(float(i.get("recurringAmount") or 0) for i in all_results if not i.get("isOptional"))

    out = [
        f"Quote {quote_id} — {total} item(s) | One-time: {_dollar(quote_total)} | Recurring: {_dollar(recurring_total)}/period",
        "",
        "| Description | Qty | UOM | Unit Price | Ext Price | Recurring | Optional | Type |",
        "|-------------|-----|-----|------------|-----------|-----------|----------|------|",
    ]
    for i in page:
        out.append(
            f"| {_trunc(i.get('shortDescription', '—'), 40)} "
            f"| {i.get('quantity', '—')} "
            f"| {i.get('uom', '—')} "
            f"| {_dollar(i.get('quoteItemPrice'))} "
            f"| {_dollar(i.get('extendedPrice'))} "
            f"| {_dollar(i.get('recurringAmount'))}/{i.get('period', '—')} "
            f"| {'Yes' if i.get('isOptional') else 'No'} "
            f"| {i.get('productType', '—')} |"
        )

    out.append(_pagination_footer(total, limit, offset))
    return "\n".join(out)


@mcp.tool()
def get_quote_tabs(quote_id: str) -> str:
    """
    List the tabs (sections) on a quote.

    Args:
        quote_id: The Sell quote ID
    """
    conditions = f'idQuote eq "{quote_id}"'
    tabs = sell_paginate("/api/quoteTabs", conditions=conditions)
    if not tabs:
        return f"No tabs found for quote {quote_id}."

    out = [f"Found {len(tabs)} tab(s) for quote {quote_id}:", "", "| ID | Name | Optional | Description |"]
    out.append("|----|------|----------|-------------|")
    for t in sorted(tabs, key=lambda x: x.get("sortOrder", 0)):
        out.append(
            f"| {t.get('id')} "
            f"| {_trunc(t.get('tabName', '—'), 30)} "
            f"| {'Yes' if t.get('isOptional') else 'No'} "
            f"| {_trunc(t.get('description', '—'), 50)} |"
        )

    return "\n".join(out)


@mcp.tool()
def get_quote_customers(quote_id: str) -> str:
    """
    List customers (contacts) associated with a quote.

    Args:
        quote_id: The Sell quote ID
    """
    customers = sell_get(f"/api/quotes/{quote_id}/customers")
    if not customers or not isinstance(customers, list):
        return f"No customers found for quote {quote_id}."

    out = [f"Found {len(customers)} customer(s) for quote {quote_id}:", "", "| Name | Account | Email | Phone | Title |"]
    out.append("|------|---------|-------|-------|-------|")
    for c in customers:
        name = f"{c.get('firstName', '')} {c.get('lastName', '')}".strip() or "—"
        out.append(
            f"| {name} "
            f"| {_trunc(c.get('accountName', '—'), 25)} "
            f"| {c.get('emailAddress', '—')} "
            f"| {c.get('dayPhone', '—')} "
            f"| {_trunc(c.get('title', '—'), 25)} |"
        )

    return "\n".join(out)


@mcp.tool()
def get_quote_terms(quote_id: str) -> str:
    """
    List financing terms configured on a quote.

    Args:
        quote_id: The Sell quote ID
    """
    terms = sell_get(f"/api/quotes/{quote_id}/quoteTerms")
    if not terms or not isinstance(terms, list):
        return f"No terms found for quote {quote_id}."

    out = [f"Found {len(terms)} term(s) for quote {quote_id}:", ""]
    for t in terms:
        out.append(f"**Term:** {t.get('termName', '—')} | Periods: {t.get('termPeriods', '—')} | Monthly: {_dollar(t.get('monthlyPayment'))}")

    return "\n".join(out)


# ══════════════════════════════════════════════════════════════════════════════
# REFERENCE DATA
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_templates() -> str:
    """
    List available quote templates.

    Use this to find template IDs for copy_quote when creating a new quote.
    """
    templates = sell_paginate("/api/templates")
    if not templates:
        return "No templates found."

    out = [f"Found {len(templates)} template(s):", "", "| ID | Name | Description |"]
    out.append("|----|------|-------------|")
    for t in templates:
        out.append(
            f"| {t.get('id')} "
            f"| {_trunc(t.get('name', '—'), 40)} "
            f"| {_trunc(t.get('shortDescription', '—'), 60)} |"
        )

    return "\n".join(out)


@mcp.tool()
def get_recurring_revenues(
    account_name: str = "",
    limit: int = 50,
    offset: int = 0,
) -> str:
    """
    List recurring revenue line items across all quotes.

    Use for: MRR pipeline visibility, recurring revenue forecasting.

    Args:
        account_name: Filter by account name (partial match, optional)
        limit: Max results per page
        offset: Pagination offset
    """
    conditions = f'accountName contains "{_safe_str(account_name)}"' if account_name else None
    fields = "id,accountName,quoteName,quoteNumber,shortDescription,recurringAmount,period,quantity,uom,isAccepted"
    all_results = sell_paginate("/api/recurringRevenues", conditions=conditions, extra={"includeFields": fields})
    total = len(all_results)
    page = all_results[offset: offset + limit]

    if not page:
        return "No recurring revenues found."

    total_mrr = sum(float(r.get("recurringAmount") or 0) for r in all_results if r.get("isAccepted"))
    out = [
        f"Found {total} recurring line(s) — Accepted MRR: {_dollar(total_mrr)}",
        "",
        "| Account | Quote | Description | Qty | Amount | Period | Accepted |",
        "|---------|-------|-------------|-----|--------|--------|----------|",
    ]
    for r in page:
        out.append(
            f"| {_trunc(r.get('accountName', '—'), 25)} "
            f"| {r.get('quoteNumber', '—')} "
            f"| {_trunc(r.get('shortDescription', '—'), 35)} "
            f"| {r.get('quantity', '—')} "
            f"| {_dollar(r.get('recurringAmount'))} "
            f"| {r.get('period', '—')} "
            f"| {'Yes' if r.get('isAccepted') else 'No'} |"
        )

    out.append(_pagination_footer(total, limit, offset))
    return "\n".join(out)


@mcp.tool()
def get_tax_codes() -> str:
    """
    List available tax codes. Use when creating or updating quotes that require tax assignment.
    """
    codes = sell_paginate("/api/taxCodes")
    if not codes:
        return "No tax codes found."

    out = [f"Found {len(codes)} tax code(s):", "", "| ID | Name | Rate |"]
    out.append("|----|------|------|")
    for c in codes:
        out.append(f"| {c.get('id')} | {c.get('name', '—')} | {c.get('rate', '—')} |")

    return "\n".join(out)


# ══════════════════════════════════════════════════════════════════════════════
# Health check
# ══════════════════════════════════════════════════════════════════════════════

@mcp.custom_route("/health", methods=["GET"])
async def _health(request: StarletteRequest) -> JSONResponse:
    return JSONResponse({"status": "healthy", "service": "cw-sell"})


if __name__ == "__main__":
    port = int(os.getenv("SELL_MCP_PORT", "8086"))
    mcp.run(transport="http", host="0.0.0.0", port=port)
