# ConnectWise Sell MCP Server

FastMCP HTTP server wrapping the ConnectWise Sell (Quosal) REST API. 12 tools covering Quotes, Line Items, Tabs, Customers, Terms, Templates, Recurring Revenue, and Tax Codes.

> **Note:** Quotes cannot be created from scratch via the Sell API — new quotes must be copied from an existing quote or template. Use `get_templates` to browse templates, then `copy_quote` to create.

## Quick start

```bash
git clone <this-repo>
cd connectwise-sell
cp .env.example .env
# fill in your SELL_* credentials
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python3 server.py
# verify: curl http://localhost:8086/health
```

## Environment variables

| Variable | Required | Default | Notes |
|---|---|---|---|
| `SELL_ACCESS_KEY` | Yes | — | Found in the Sell URL parameters when logged in |
| `SELL_USERNAME` | Yes | — | Sell API username (must be an API user) |
| `SELL_PASSWORD` | Yes | — | Sell API password |
| `SELL_BASE_URL` | No | `https://sellapi.quosalsell.com` | Override if your instance uses a different host |
| `MCP_AUTH_TOKEN` | No | — | Bearer token for MCP client auth; omit to run without auth |
| `SELL_MCP_PORT` | No | `8086` | HTTP listen port |

### How to find your access key

Log into ConnectWise Sell and look at the URL — it will contain a parameter like `accessKey=XXXXXXXX`. That value is your `SELL_ACCESS_KEY`.

## Authentication

The Sell API uses HTTP Basic auth with a compound credential:

```
Authorization: basic base64(accessKey+username:password)
```

The server constructs this automatically from your env vars.

## Tools (12)

**Quotes (5):** `list_quotes`, `get_quote`, `get_quote_versions`, `copy_quote`, `update_quote`

**Quote detail (4):** `get_quote_items`, `get_quote_tabs`, `get_quote_customers`, `get_quote_terms`

**Reference (3):** `get_templates`, `get_recurring_revenues`, `get_tax_codes`

## Claude Desktop / Claude Code configuration

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json` on Mac, `%APPDATA%\Claude\claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "connectwise-sell": {
      "type": "http",
      "url": "http://localhost:8086/mcp",
      "headers": {
        "Authorization": "Bearer your_token_here"
      }
    }
  }
}
```

## Running as a service

```ini
[Unit]
Description=ConnectWise Sell MCP
After=network.target

[Service]
User=mcp
WorkingDirectory=/opt/connectwise-sell-mcp
EnvironmentFile=/opt/connectwise-sell-mcp/.env
ExecStart=/opt/connectwise-sell-mcp/venv/bin/python3 server.py
Restart=always

[Install]
WantedBy=multi-user.target
```

## Related

- [connectwise-mcp](https://github.com/Mfrostbutter/connectwise-mcp) — ConnectWise Manage MCP server (tickets, agreements, companies, time, finance)

## License

MIT
