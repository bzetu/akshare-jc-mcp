# akshare-jc-mcp

Unified MCP server for Chinese stock (A-share) market data.

## Why akshare-jc-mcp?

| 痛点 | 本项目的解决方式 |
|------|----------------|
| 多个工具各自独立，LLM要调4-7次才能凑齐数据 | **单个`get_data`工具**，一次请求所有 features 并发拉取，一次返回 |
| akshare 某些接口不稳定（东方财富断连、概念板块查不到） | 直连 push2delay API + fallback 机制，不依赖 akshare 不稳定接口 |
| 新闻只有摘要片段，没有正文 | 自动抓取全文，返回完整文章内容 |
| 技术指标要自己算，代码容易写错 | 服务端预计算 **KDJ/MACD/RSI/BOLL/SMA**，默认即带回 |
| 月K/年K数据量过大（336条→150KB）导致 MCP 传输截断 | 按 interval 独立截断：日K默认120条、周K 52条、月K 36条、年K 10条，payload 可控 |
| 限售解禁和增发数据分散，解禁成本靠猜 | 自动匹配增发数据，按锁定期计算**参考增发价** |

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

Add to your MCP client config (Claude Desktop, Cursor, etc.):

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

Requires Python 3.11+ and a working `akshare` installation (auto-installed as dependency).

## Tool: `get_data`

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `symbol` | `string` | Yes | — | Stock code (e.g. `000625`, `600519`) |
| `features` | `array[string]` | Yes | — | List of data features to fetch |
| `news_recent_n` | `int` | No | 10 | Number of recent news records |
| `recent_n` | `int` | No | 3 | Number of recent financial statement periods |
| `hist_interval` | `string` | No | `"day"` | K-line interval: `1min`, `day`, `week`, `month`, `year` |
| `hist_indicators` | `array[string]` | No | `["KDJ","MACD","RSI","BOLL","SMA"]` | Technical indicators for hist_data |
| `hist_day_n` | `int` | No | 120 | Number of daily K-line bars to return |
| `hist_week_n` | `int` | No | 52 | Number of weekly K-line bars to return |
| `hist_month_n` | `int` | No | 36 | Number of monthly K-line bars to return |
| `hist_year_n` | `int` | No | 10 | Number of yearly K-line bars to return |
| `hist_analysis` | `bool` | No | `false` | Return compact P0 technical analysis alongside raw K-line data |
| `hist_raw_n` | `int` | No | `null` | With `hist_analysis=true`, number of trailing raw rows to include; `0` returns analysis only |

### Features

| Feature | Description | Data Source |
|---------|-------------|-------------|
| `news` | Recent news with full article text (no URLs) | East Money |
| `inner_trade` | Insider trading / block trade records | 雪球 |
| `financial` | Key financial metrics by reporting period | 同花顺 |
| `fund_flow` | Daily fund flow (main force / super-large / large / medium / small orders) | East Money push API |
| `concept` | Concept board tags belonging to the stock | East Money push2delay |
| `hsgt_summary` | North-bound / South-bound capital flow summary | East Money |
| `hist_data` | K-line data with optional technical indicators. Supports `1min`/`day`/`month`/`year` intervals | akshare (腾讯) |
| `realtime` | Real-time snap quote | 腾讯 |
| `time_info` | Current system time + last trading day | Sina + local |
| `restricted_release` | Restricted share unlock schedule (date, volume, ratio) | East Money |
| `additional_issuance` | Additional issuance / private placement history | East Money |

### Typical Usage

**消息面+基本面查询（一次性获取全部）：**

```markdown
    get_data(symbol="600733", features=["news", "inner_trade", "financial", "fund_flow", "concept", "hsgt_summary"], news_recent_n=10, recent_n=3)
```

**日K技术分析（默认120条，约6个月）：**

```markdown
    get_data(symbol="600733", features=["hist_data", "realtime"], hist_interval="day", hist_day_n=120, hist_indicators=["KDJ","MACD","RSI","BOLL","SMA"])
```

**月K长线趋势（默认36个月=3年）：**

```markdown
    get_data(symbol="600733", features=["hist_data", "realtime"], hist_interval="month", hist_month_n=36, hist_indicators=["KDJ","MACD","RSI","BOLL","SMA"])
```

**预计算技术分析（保持默认返回兼容，显式开启）：**

```markdown
    get_data(symbol="600733", features=["hist_data"], hist_analysis=true)
```

With `hist_analysis=true`, `hist_data.data` becomes `{"raw": [...], "analysis": {...}}`. The analysis is compact: MA/MACD/RSI/KDJ/BOLL/volume state, regression trend, MACD divergence, support/resistance, single/multi-bar patterns, double-top/double-bottom candidates, latest cross events, and an evidence-backed mechanical score. `bar_period_end` is the period label for weekly/monthly bars; `source_last_trading_day` is the actual latest underlying daily session. An unfinished period is marked `intraday_partial`. Major patterns use explicit `candidate`, `confirmed`, and `invalidated` statuses, and their key points identify whether they came from `high` or `low`. Minute K-lines skip divergence, support/resistance, and pattern detection. The default response remains the original raw array.

For compact multi-timeframe reports, set `hist_raw_n=0` for analysis-only month/week requests and `hist_raw_n=10` for a daily request that needs recent candles. `hist_raw_n` only changes the returned `raw` array; the complete requested history is still used to calculate `analysis`.

**年K超长线（默认10年）：**

```markdown
    get_data(symbol="600733", features=["hist_data", "realtime"], hist_interval="year", hist_year_n=10, hist_indicators=["KDJ","MACD","RSI","BOLL","SMA"])
```

**1分钟K盘中超短线（仅交易时段有数据，全天最多480条）：**

```markdown
    get_data(symbol="600733", features=["hist_data", "realtime"], hist_interval="1min", hist_indicators=["KDJ","MACD","RSI","BOLL","SMA"])
```

**限售解禁+增发数据（计算解禁成本）：**

```markdown
    get_data(symbol="600733", features=["restricted_release", "additional_issuance"])
```

### Response Format

JSON array, one entry per feature:

```json
[
  {"feature": "news", "data": [...], "error": false, "error_reason": null},
  {"feature": "fund_flow", "data": [...], "error": false, "error_reason": null},
  ...
]
```

`error: true` means the feature failed — LLM should fall back to web search or inform the user.

## Design & Reliability

### Problems Solved

| Problem | Solution |
|---------|----------|
| LLM makes 4-7 tool calls per request (news + insider_trade + financial + balance_sheet + ...) | Single `get_data` call accepts all features at once via concurrent.futures |
| akshare `stock_board_concept_cons_em(symbol)` takes **stock code** but expects a **board name** → returns empty | Rewrote with direct `push2delay` API: `f129` field returns comma-separated concept names in one call |
| akshare concurrent calls trigger eastmoney `RemoteDisconnected` (connection pool exhaustion) | Shared `requests.Session` with connection reuse; `fund_flow` uses `push2delay` as fallback when `push2his` drops |
| akshare `stock_news_em()` returns truncated snippets | `_fetch_article_text` fetches full HTML and extracts article body per feature section |
| Sina financial statements (balance_sheet / income_statement / cash_flow) were too large (~18-26KB each) and semantically duplicate with `financial` | Removed; `recent_n=3` reports-only mode keeps payload under 2KB |
| LLM was seeing news URLs and trying to fetch them manually | `r.pop("新闻链接", None)` before returning |

### Reliability

All HTTP calls share a single `requests.Session` to minimize connection overhead. Features that depend on eastmoney APIs fall back to alternative endpoints (`push2delay` when `push2/push2his` are unavailable). Total 6-feature fetch (`news`+`inner_trade`+`financial`+`fund_flow`+`concept`+`hsgt_summary`) completes in **2-3s** (~15KB).

## Development

```bash
pip install -e .
python -c "from akshare_jc_mcp.server import mcp; print(mcp.name)"
```

## License

MIT
