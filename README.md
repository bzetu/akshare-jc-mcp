# akshare-jc-mcp

Unified MCP server for Chinese stock (A-share) market data.

Replaces the multi-tool approach (like `akshare-one-mcp`) with a **single `get_data` tool** that accepts a list of requested features and returns all results in one response. This dramatically reduces LLM tool calls — from 4-7 per request down to 1.

## Install

```bash
pip install git+https://github.com/bzetu/akshare-jc-mcp
```

Or for development:

```bash
git clone https://github.com/bzetu/akshare-jc-mcp
cd akshare-jc-mcp
pip install -e .
```

## MCP Configuration

Add to your Hermes / Claude Desktop MCP config:

```json
{
  "mcpServers": {
    "akshare-jc": {
      "command": "python3.13",
      "args": ["-m", "akshare_jc_mcp"]
    }
  }
}
```

Requires Python 3.10+ and a working `akshare` installation (auto-installed as dependency).

## Tool: `get_data`

The single endpoint for all data needs.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `symbol` | `string` | Yes | — | Stock code (e.g. `000625`, `600519`) |
| `features` | `array[string]` | Yes | — | List of data features to fetch |

### Feature list

| Feature | Description |
|---------|-------------|
| `news` | Recent news related to the stock |
| `inner_trade` | Insider trading / block trade records |
| `financial` | Key financial metrics (PE, PB, ROE, revenue, profit) |
| `balance_sheet` | Balance sheet (total assets, liabilities, equity) |
| `income_statement` | Income statement (revenue, cost, profit breakdown) |
| `cash_flow` | Cash flow statement (operating/investing/financing) |
| `hist_data` | Daily K-line with optional technical indicators |
| `realtime` | Real-time snap quote |
| `time_info` | Current system time + last trading day |

### Example Usage (in SOUL.md)

**Sentinel — data gathering:**

```markdown
Ask akshare-jc-mcp for news, insider trading, and financial data all at once:

    get_data(symbol="000625", features=["news", "inner_trade", "financial"])

If a feature returns error: true, fall back to web_search for that aspect.
```

**Prism — technical analysis:**

```markdown
Ask akshare-jc-mcp for historical data with indicators:

    get_data(symbol="000625", features=["hist_data"])

All indicators (KDJ, MACD, RSI, BOLL, SMA) are computed automatically.
```

### Response Format

The tool returns a JSON array of objects, one per feature:

```json
[
  {
    "feature": "news",
    "data": [
      {"title": "...", "date": "2026-07-07", "content": "..."},
      ...
    ],
    "error": false,
    "error_reason": null
  },
  {
    "feature": "inner_trade",
    "data": [...],
    "error": false,
    "error_reason": null
  },
  {
    "feature": "financial",
    "data": null,
    "error": true,
    "error_reason": "API request failed: connection timeout"
  }
]
```

**Important**: When a feature has `error: true`, the LLM should handle it gracefully (e.g. fall back to web search or inform the user).

## Development

```bash
# Clone and install
git clone https://github.com/bzetu/akshare-jc-mcp
cd akshare-jc-mcp
pip install -e .

# Test
python -c "from akshare_jc_mcp.server import mcp; print(mcp.name)"
```

## License

MIT
