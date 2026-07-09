import json
import re
import html
import sys
import traceback
import concurrent.futures
from datetime import datetime
from typing import Annotated

import pandas as pd
import numpy as np
import requests
import akshare as ak
from fastmcp import FastMCP

mcp = FastMCP(name="akshare-jc-mcp")

_session = requests.Session()
_session.headers.update({"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"})


def _exchange_lower(symbol: str) -> str:
    if symbol[0] in "023":
        return "sz"
    if symbol[0] in "48":
        return "bj"
    return "sh"


def _get_sma(df: pd.Series, window: int = 20) -> pd.DataFrame:
    return df.rolling(window=window).mean().to_frame(name=f"SMA_{window}")


def _get_ema(df: pd.Series, window: int = 20) -> pd.DataFrame:
    return df.ewm(span=window, adjust=False).mean().to_frame(name=f"EMA_{window}")


def _get_rsi(close: pd.Series, window: int = 14) -> pd.DataFrame:
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.to_frame(name="RSI")


def _get_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd_bar = 2 * (dif - dea)
    return pd.DataFrame({"DIF": dif, "DEA": dea, "MACD_bar": macd_bar})


def _get_bollinger_bands(close: pd.Series, window: int = 20, std: int = 2) -> pd.DataFrame:
    sma = close.rolling(window=window).mean()
    std_val = close.rolling(window=window).std()
    return pd.DataFrame({
        "BOLL_mid": sma,
        "BOLL_upper": sma + std_val * std,
        "BOLL_lower": sma - std_val * std,
    })


def _get_stoch(df_high: pd.Series, df_low: pd.Series, df_close: pd.Series, window: int = 14, smooth_k: int = 3, smooth_d: int = 3) -> pd.DataFrame:
    low_min = df_low.rolling(window=window).min()
    high_max = df_high.rolling(window=window).max()
    rsv = ((df_close - low_min) / (high_max - low_min).replace(0, np.nan)) * 100
    k = rsv.rolling(window=smooth_k).mean()
    d = k.rolling(window=smooth_d).mean()
    return pd.DataFrame({"K": k, "D": d, "J": 3 * k - 2 * d})


_HIST_INDICATOR_MAP = {
    "SMA": (_get_sma, {"window": 20}),
    "EMA": (_get_ema, {"window": 20}),
    "RSI": (_get_rsi, {"window": 14}),
    "MACD": (_get_macd, {"fast": 12, "slow": 26, "signal": 9}),
    "BOLL": (_get_bollinger_bands, {"window": 20, "std": 2}),
    "KDJ": (_get_stoch, {"window": 14, "smooth_d": 3, "smooth_k": 3}),
}


def _tencent_realtime(symbol: str) -> dict:
    exchange = _exchange_lower(symbol)
    url = f"https://qt.gtimg.cn/q={exchange}{symbol}"
    resp = _session.get(url, timeout=10)
    resp.encoding = "gbk"
    text = resp.text.strip()
    if "=" not in text or '"' not in text:
        return {"feature": "realtime", "data": None, "error": True, "error_reason": f"Unexpected response: {text[:200]}"}
    fields = text.split('"')[1].split("~") if '"' in text else []
    if len(fields) < 6:
        return {"feature": "realtime", "data": None, "error": True, "error_reason": f"Too few fields: {len(fields)}"}
    return {
        "feature": "realtime",
        "data": {
            "market": fields[0],
            "name": fields[1],
            "code": fields[2],
            "price": fields[3],
            "yesterday_close": fields[4],
            "open": fields[5],
            "volume": fields[6],
        },
        "error": False,
        "error_reason": None,
    }


def _df_to_list(df: pd.DataFrame) -> list:
    records = json.loads(df.to_json(orient="records", force_ascii=False))
    return [{k: v for k, v in r.items() if v is not None} for r in records]


def _fetch_article_text(url: str) -> str | None:
    try:
        resp = _session.get(url, timeout=10)
        resp.encoding = "utf-8"
        text = resp.text
        for pattern in [
            r'<div[^>]*class="[^"]*article-body[^"]*"[^>]*>(.*?)</div>',
            r'<div[^>]*class="[^"]*Body[^"]*"[^>]*>(.*?)</div>',
            r'<div[^>]*class="[^"]*main-text[^"]*"[^>]*>(.*?)</div>',
            r'<div[^>]*id="[^"]*content[^"]*"[^>]*>(.*?)</div>',
            r'<article[^>]*>(.*?)</article>',
        ]:
            m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            if m:
                content = m.group(1)
                content = re.sub(r'<[^>]+>', "", content)
                content = html.unescape(content)
                content = re.sub(r'\s+', " ", content).strip()
                if len(content) > 100:
                    return content[:3000]
        return None
    except Exception:
        return None


def _call_feature(feature: str, symbol: str, kwargs: dict) -> dict:
    try:
        if feature == "news":
            df = ak.stock_news_em(symbol=symbol)
            n = kwargs.get("news_recent_n")
            if n is not None:
                df = df.tail(n)
            records = _df_to_list(df)
            urls = [r.get("新闻链接") for r in records if r.get("新闻链接")]
            if urls:
                with concurrent.futures.ThreadPoolExecutor(max_workers=len(urls)) as pool:
                    texts = list(pool.map(_fetch_article_text, urls))
                for r, t in zip(records, texts):
                    if t:
                        r["新闻内容"] = t
            for r in records:
                r.pop("新闻链接", None)
            return {"feature": feature, "data": records, "error": False, "error_reason": None}

        elif feature == "inner_trade":
            df = ak.stock_inner_trade_xq()
            df = df[df["股票代码"].astype(str) == symbol]
            return {"feature": feature, "data": _df_to_list(df), "error": False, "error_reason": None}

        elif feature == "financial":
            df = ak.stock_financial_abstract_ths(symbol=symbol, indicator="按报告期")
            n = kwargs.get("recent_n")
            if n is not None:
                df = df.tail(n)
            return {"feature": feature, "data": _df_to_list(df), "error": False, "error_reason": None}

        elif feature == "hist_data":
            interval = kwargs.get("hist_interval", "day")
            exchange = _exchange_lower(symbol)
            df = ak.stock_zh_a_daily(symbol=f"{exchange}{symbol}", adjust="qfq")
            df = df.rename(columns={"date": "timestamp"})
            df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize("Asia/Shanghai")
            df["volume"] = df["volume"].astype("int64")
            df = df[["timestamp", "open", "high", "low", "close", "volume"]]
            indicators_list = kwargs.get("hist_indicators") or []
            if indicators_list:
                temp = []
                for ind in indicators_list:
                    key = ind.upper()
                    if key in _HIST_INDICATOR_MAP:
                        func, params = _HIST_INDICATOR_MAP[key]
                        if key == "KDJ":
                            indicator_df = func(df["high"], df["low"], df["close"], **params)
                        else:
                            indicator_df = func(df["close"], **params)
                        temp.append(indicator_df)
                if temp:
                    df = df.join(temp)
            recent_n = kwargs.get("hist_recent_n", 120)
            if recent_n is not None:
                df = df.tail(recent_n)
            return {"feature": feature, "data": _df_to_list(df), "error": False, "error_reason": None}

        elif feature == "realtime":
            return _tencent_realtime(symbol)

        elif feature == "fund_flow":
            exchange = "1" if _exchange_lower(symbol) == "sh" else "0"
            records = []

            # Try push2his (5-day history with full breakdown)
            try:
                url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
                params = {"secid": f"{exchange}.{symbol}", "fields1": "f1,f2,f3,f7", "fields2": "f51,f52,f53,f54,f55,f56,f57", "lmt": "5"}
                resp = _session.get(url, params=params, timeout=5)
                data = resp.json()
                if data.get("data") and data["data"].get("klines"):
                    for line in data["data"]["klines"]:
                        parts = line.split(",")
                        if len(parts) >= 7:
                            records.append({
                                "日期": parts[0],
                                "主力净流入": parts[1],
                                "超大单净流入": parts[2],
                                "大单净流入": parts[3],
                                "中单净流入": parts[4],
                                "小单净流入": parts[5],
                                "主力净流入占比": parts[6],
                            })
            except Exception:
                pass

            # Fallback: push2delay (today's breakdown) + f178 trend
            if not records:
                try:
                    url = "https://push2delay.eastmoney.com/api/qt/stock/fflow/daykline/get"
                    params = {"secid": f"{exchange}.{symbol}", "fields1": "f1,f2,f3,f7", "fields2": "f51,f52,f53,f54,f55,f56,f57", "lmt": "5"}
                    resp = _session.get(url, params=params, timeout=5)
                    data = resp.json()
                    if data.get("data") and data["data"].get("klines"):
                        for line in data["data"]["klines"]:
                            parts = line.split(",")
                            if len(parts) >= 7:
                                records.append({
                                    "日期": parts[0],
                                    "主力净流入": parts[1],
                                    "超大单净流入": parts[2],
                                    "大单净流入": parts[3],
                                    "中单净流入": parts[4],
                                    "小单净流入": parts[5],
                                    "主力净流入占比": parts[6],
                                })
                    # Supplement with f178 historical trend
                    url2 = "https://29.push2delay.eastmoney.com/api/qt/stock/get"
                    params2 = {"secid": f"{exchange}.{symbol}", "ut": "bd1d9ddb04089700cf9c27f6f7426281", "fltt": "2", "invt": "2", "fields": "f57,f58,f178"}
                    resp2 = _session.get(url2, params=params2, timeout=5)
                    data2 = resp2.json()
                    if data2.get("data") and data2["data"].get("f178"):
                        import json as _json
                        hist = _json.loads(data2["data"]["f178"]) if isinstance(data2["data"]["f178"], str) else data2["data"]["f178"]
                        today_date = records[0]["日期"] if records else None
                        for h in hist:
                            if h["date"] != today_date:
                                records.append({"日期": h["date"], "主力净流入": str(h["mainNetAmt"])})
                except Exception:
                    pass

            records.sort(key=lambda r: r["日期"], reverse=True) if records else None
            return {"feature": feature, "data": records, "error": False, "error_reason": None}

        elif feature == "concept":
            try:
                exchange = "1" if _exchange_lower(symbol) == "sh" else "0"
                url = "https://29.push2delay.eastmoney.com/api/qt/stock/get"
                params = {
                    "secid": f"{exchange}.{symbol}",
                    "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                    "fltt": "2",
                    "invt": "2",
                    "fields": "f57,f58,f127,f128,f129",
                }
                resp = _session.get(url, params=params, timeout=10)
                data = resp.json().get("data", {})
                concepts = []
                if data.get("f129"):
                    for name in str(data["f129"]).split(","):
                        if name.strip():
                            concepts.append({"概念名称": name.strip()})
                return {"feature": feature, "data": concepts, "error": False, "error_reason": None}
            except Exception:
                return {"feature": feature, "data": [], "error": False, "error_reason": None}

        elif feature == "hsgt_summary":
            df = ak.stock_hsgt_fund_flow_summary_em()
            return {"feature": feature, "data": _df_to_list(df), "error": False, "error_reason": None}

        elif feature == "time_info":
            local_time = datetime.now().astimezone()
            current_date = local_time.date()
            trade_date_df = ak.tool_trade_date_hist_sina()
            trade_dates = [d for d in trade_date_df["trade_date"]]
            past_dates = sorted([d for d in trade_dates if d <= current_date], reverse=True)
            last_trading_day = past_dates[0].strftime("%Y-%m-%d") if past_dates else None
            return {
                "feature": feature,
                "data": {
                    "iso_format": local_time.isoformat(),
                    "timestamp": local_time.timestamp(),
                    "last_trading_day": last_trading_day,
                },
                "error": False,
                "error_reason": None,
            }

        else:
            return {"feature": feature, "data": None, "error": True, "error_reason": f"Unknown feature: {feature}"}

    except Exception as e:
        return {
            "feature": feature,
            "data": None,
            "error": True,
            "error_reason": f"{type(e).__name__}: {e}",
        }


@mcp.tool
def get_data(
    symbol: Annotated[str, "Stock symbol/ticker (e.g. '000001')"],
    features: Annotated[list[str], "REQUIRED: ALL features needed in ONE call. DO NOT make multiple get_data calls — batch everything here. Supported: news, inner_trade, financial, fund_flow, concept, hsgt_summary, hist_data, realtime, time_info"],
    news_recent_n: Annotated[int | None, "Number of most recent news records"] = 10,
    recent_n: Annotated[int | None, "Number of most recent financial statement records"] = 3,
    hist_interval: Annotated[str, "K-line interval for hist_data (minute/hour/day/week/month/year)"] = "day",
    hist_indicators: Annotated[list[str] | None, "Technical indicators for hist_data (e.g. KDJ, MACD, RSI, BOLL, SMA)"] = None,
    hist_recent_n: Annotated[int | None, "Number of most recent hist_data records"] = 120,
) -> str:
    """SINGLE-CALL batch stock data fetcher. Returns JSON array with ALL requested features' data in one response.

    Logs call details to stderr for debugging.

    ⚠️ CRITICAL: Pass ALL desired features in 'features' list at once. Multiple get_data calls for the same symbol are wasteful and prohibited — this tool is designed for batch querying.

    Each result entry has: {feature, data, error, error_reason}.

    Example:
      get_data(symbol="000625", features=["news", "inner_trade", "financial", "fund_flow", "concept", "hsgt_summary"], news_recent_n=10, recent_n=3)
      get_data(symbol="000625", features=["hist_data"], hist_indicators=["KDJ","MACD","RSI","BOLL","SMA"])
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] get_data called: symbol={symbol}, features={features}, news_recent_n={news_recent_n}, recent_n={recent_n}, hist_interval={hist_interval}, hist_indicators={hist_indicators}, hist_recent_n={hist_recent_n}", file=sys.stderr, flush=True)
    kwargs = {
        "news_recent_n": news_recent_n,
        "recent_n": recent_n,
        "hist_interval": hist_interval,
        "hist_indicators": hist_indicators or [],
        "hist_recent_n": hist_recent_n,
    }
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(features)) as pool:
        futures = {pool.submit(_call_feature, f, symbol, kwargs): f for f in features}
        results = [f.result() for f in concurrent.futures.as_completed(futures)]
    payload = json.dumps(results, ensure_ascii=False)
    for r in results:
        data_len = len(json.dumps(r.get("data", ""), ensure_ascii=False)) if r.get("data") else 0
        print(f"  [{r.get('feature')}] error={r.get('error')}, data_chars={data_len}", file=sys.stderr, flush=True)
    print(f"  total={len(payload)} chars", file=sys.stderr, flush=True)
    return payload
