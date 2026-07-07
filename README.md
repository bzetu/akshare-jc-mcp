# akshare-jc-mcp

Unified MCP server for Chinese stock market data.

Replaces `akshare-one-mcp` with a single `get_data` tool that batches multiple data requests into one call.

## Install

```bash
pip install git+https://github.com/charles/akshare-jc-mcp
```

Or for development:

```bash
git clone https://github.com/charles/akshare-jc-mcp
cd akshare-jc-mcp
pip install -e .
```

## Usage

```python
# Get news + insider trading + financial metrics in one call
get_data(symbol="000625", features=["news", "inner_trade", "financial"])

# Get historical K-line with technical indicators (for Prism)
get_data(symbol="000625", features=["hist_data"],
         hist_indicators=["KDJ","MACD","RSI","BOLL","SMA"])
```

## Features

| Feature | Description |
|---------|-------------|
| `news` | Stock-related news |
| `inner_trade` | Insider trading data |
| `financial` | Key financial metrics |
| `balance_sheet` | Balance sheet |
| `income_statement` | Income statement |
| `cash_flow` | Cash flow statement |
| `hist_data` | Historical K-line + indicators |
| `realtime` | Real-time market data |
| `time_info` | Current time + last trading day |
