import json
import re
import html
import sys
import time
import traceback
import concurrent.futures
from datetime import datetime, date
from typing import Annotated

import pandas as pd
import numpy as np
import requests
import akshare as ak
from fastmcp import FastMCP

mcp = FastMCP(name="akshare-jc-mcp")

_session = requests.Session()
_session.headers.update({"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"})

_trade_dates_cache: list[date] | None = None


def _last_trading_day(d: date | None = None) -> str:
    global _trade_dates_cache
    if _trade_dates_cache is None:
        df = ak.tool_trade_date_hist_sina()
        raw = df["trade_date"].tolist()
        _trade_dates_cache = sorted([
            (pd.Timestamp(v).date() if not isinstance(v, date) else v) for v in raw
        ])
    target = d or datetime.now().date()
    past = [td for td in _trade_dates_cache if td <= target]
    return past[-1].strftime("%Y%m%d") if past else target.strftime("%Y%m%d")

_MINUTE_KLT_MAP = {"1min": "1"}


def _exchange_secid(symbol: str) -> str:
    prefix = _exchange_lower(symbol)
    return {"sh": "1", "sz": "0", "bj": "2"}.get(prefix, "1")


def _fetch_minute_kline(symbol: str) -> pd.DataFrame:
    secid = f"{_exchange_secid(symbol)}.{symbol}"
    today = datetime.now().strftime("%Y%m%d")
    push2delay = "https://push2delay.eastmoney.com/api/qt/stock/kline/get"
    push2his = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

    for url in [push2delay, push2his]:
        try:
            params = {
                "secid": secid,
                "fields1": "f1,f2,f3,f4,f5",
                "fields2": "f51,f52,f53,f54,f55,f56,f57",
                "klt": "1",
                "fqt": "1",
                "end": today,
                "lmt": "480",
            }
            resp = _session.get(url, params=params, timeout=5)
            raw = (resp.json().get("data") or {}).get("klines") or []
            if raw:
                return _parse_kline_lines(raw)
        except Exception:
            pass

    return pd.DataFrame()


def _parse_kline_lines(lines: list[str]) -> pd.DataFrame:
    rows = []
    for line in lines:
        parts = line.split(",")
        if len(parts) < 7:
            continue
        rows.append({
            "timestamp": pd.Timestamp(parts[0]),
            "open": float(parts[1]),
            "close": float(parts[2]),
            "high": float(parts[3]),
            "low": float(parts[4]),
            "volume": int(float(parts[5])),
        })
    return pd.DataFrame(rows)


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
    records = json.loads(df.to_json(orient="records", force_ascii=False, date_format="iso"))
    return [{k: v for k, v in r.items() if v is not None} for r in records]


def _number(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), 4)


def _latest_cross(fast: pd.Series, slow: pd.Series) -> dict | None:
    valid = pd.DataFrame({"fast": fast, "slow": slow}).dropna()
    if len(valid) < 2:
        return None
    direction = (valid["fast"] > valid["slow"]).astype(int)
    changes = direction[direction.ne(direction.shift())]
    changes = changes.iloc[1:]
    if changes.empty:
        return None
    timestamp = changes.index[-1]
    return {
        "direction": "golden" if changes.iloc[-1] else "dead",
        "timestamp": timestamp.strftime("%Y-%m-%d %H:%M") if isinstance(timestamp, pd.Timestamp) else str(timestamp),
        "bars_ago": len(valid) - valid.index.get_loc(timestamp) - 1,
    }


def _timestamp(value, minute: bool = False) -> str:
    return value.strftime("%Y-%m-%d %H:%M" if minute else "%Y-%m-%d") if isinstance(value, pd.Timestamp) else str(value)


def _trend_analysis(close: pd.Series, interval: str) -> dict:
    windows = {"day": 20, "week": 12, "weekly": 12, "month": 8, "monthly": 8, "year": 5, "yearly": 5, "1min": 30}
    sample = close.dropna().tail(windows.get(interval, 20))
    if len(sample) < 3 or sample.iloc[0] == 0:
        return {"slope_abs": None, "slope_pct_per_bar": None, "r_squared": None, "strength": None, "direction": None}
    x = np.arange(len(sample))
    slope, intercept = np.polyfit(x, sample.to_numpy(), 1)
    fitted = slope * x + intercept
    total = np.sum((sample.to_numpy() - sample.mean()) ** 2)
    r_squared = 1 - np.sum((sample.to_numpy() - fitted) ** 2) / total if total else 0
    slope_pct = slope / sample.iloc[0] * 100
    direction = "up" if slope_pct > 0.15 else ("down" if slope_pct < -0.15 else "flat")
    strength = "strong" if r_squared >= 0.7 else ("moderate" if r_squared >= 0.4 else "weak")
    return {"slope_abs": _number(slope), "slope_pct_per_bar": _number(slope_pct), "r_squared": _number(r_squared), "strength": strength, "direction": direction}


def _pivot_positions(series: pd.Series, kind: str) -> list[int]:
    values = series.to_numpy()
    return [i for i in range(1, len(values) - 1) if pd.notna(values[i]) and ((values[i] <= values[i - 1] and values[i] < values[i + 1]) if kind == "low" else (values[i] >= values[i - 1] and values[i] > values[i + 1]))]


def _macd_divergence(close: pd.Series, dif: pd.Series, interval: str) -> dict:
    empty = {"detected": False, "confirmed": False, "strength": None, "point_a": None, "point_b": None, "confirmation_level": None, "invalidation_level": None}
    if interval in _MINUTE_KLT_MAP or interval in ("year", "yearly"):
        return {"bullish": empty, "bearish": empty}
    span = {"day": 30, "week": 20, "weekly": 20, "month": 12, "monthly": 12}.get(interval, 30)
    prices = close.tail(span)
    macd = dif.reindex(prices.index)

    def detect(kind: str) -> dict:
        positions = _pivot_positions(prices, kind)
        if len(positions) < 2:
            return empty.copy()
        a, b = positions[-2:]
        price_a, price_b, dif_a, dif_b = prices.iloc[a], prices.iloc[b], macd.iloc[a], macd.iloc[b]
        if pd.isna(dif_a) or pd.isna(dif_b):
            return empty.copy()
        detected = bool(price_b < price_a and dif_b > dif_a) if kind == "low" else bool(price_b > price_a and dif_b < dif_a)
        if not detected:
            return empty.copy()
        between = prices.iloc[a:b + 1]
        confirmation = between.max() if kind == "low" else between.min()
        confirmed = bool(prices.iloc[-1] > confirmation) if kind == "low" else bool(prices.iloc[-1] < confirmation)
        separation = abs((price_b / price_a - 1) * 100) + abs(dif_b - dif_a)
        return {
            "detected": True,
            "confirmed": confirmed,
            "strength": "strong" if separation >= 8 else "moderate",
            "point_a": {"timestamp": _timestamp(prices.index[a]), "price": _number(price_a), "dif": _number(dif_a)},
            "point_b": {"timestamp": _timestamp(prices.index[b]), "price": _number(price_b), "dif": _number(dif_b)},
            "confirmation_level": _number(confirmation),
            "invalidation_level": _number(price_b),
        }

    return {"bullish": detect("low"), "bearish": detect("high")}


def _support_resistance(high: pd.Series, low: pd.Series, close: pd.Series, interval: str) -> dict:
    if interval in _MINUTE_KLT_MAP or len(close) < 5:
        return {"support_levels": [], "resistance_levels": []}
    true_range = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr = true_range.rolling(14).mean().iloc[-1]
    threshold = max(abs(close.iloc[-1]) * 0.01, 0 if pd.isna(atr) else atr * 0.5)

    def levels(series: pd.Series, kind: str) -> list[dict]:
        positions = _pivot_positions(series, "low" if kind == "support" else "high")
        clusters = []
        for pos in positions:
            value = series.iloc[pos]
            for cluster in clusters:
                if abs(value - cluster["value"]) <= threshold:
                    cluster["values"].append((pos, value))
                    cluster["value"] = sum(v for _, v in cluster["values"]) / len(cluster["values"])
                    break
            else:
                clusters.append({"value": value, "values": [(pos, value)]})
        relevant = [c for c in clusters if (c["value"] <= close.iloc[-1] if kind == "support" else c["value"] >= close.iloc[-1])]
        relevant.sort(key=lambda c: abs(c["value"] - close.iloc[-1]))
        return [{"price": _number(c["value"]), "touches": len(c["values"]), "latest_timestamp": _timestamp(series.index[c["values"][-1][0]]), "distance_pct": _number((c["value"] / close.iloc[-1] - 1) * 100), "strength": "strong" if len(c["values"]) >= 3 else ("moderate" if len(c["values"]) == 2 else "weak")} for c in relevant[:3]]

    return {"support_levels": levels(low, "support"), "resistance_levels": levels(high, "resistance")}


def _single_patterns(df: pd.DataFrame, interval: str) -> list[dict]:
    if interval in _MINUTE_KLT_MAP or df.empty:
        return []
    bar = df.iloc[-1]
    body, range_ = abs(bar["close"] - bar["open"]), bar["high"] - bar["low"]
    if range_ <= 0:
        return []
    upper, lower = bar["high"] - max(bar["open"], bar["close"]), min(bar["open"], bar["close"]) - bar["low"]
    result, timestamp = [], _timestamp(df.index[-1])
    if body / range_ <= 0.1:
        result.append({"name": "doji", "timestamp": timestamp, "strict_match": True, "body_ratio": _number(body / range_), "upper_shadow_ratio": _number(upper / range_), "lower_shadow_ratio": _number(lower / range_), "confirmation_next_bar": False})
    elif lower >= body * 2 and upper <= body and body / range_ <= 0.4:
        result.append({"name": "hammer", "timestamp": timestamp, "strict_match": True, "body_ratio": _number(body / range_), "upper_shadow_ratio": _number(upper / range_), "lower_shadow_ratio": _number(lower / range_), "confirmation_next_bar": False})
    elif body / range_ >= 0.75:
        result.append({"name": "long_bullish" if bar["close"] > bar["open"] else "long_bearish", "timestamp": timestamp, "strict_match": True, "body_ratio": _number(body / range_), "upper_shadow_ratio": _number(upper / range_), "lower_shadow_ratio": _number(lower / range_), "confirmation_next_bar": False})
    return result


def _multi_patterns(df: pd.DataFrame, interval: str) -> list[dict]:
    if interval in _MINUTE_KLT_MAP or len(df) < 2:
        return []
    bars = df.iloc[-3:]
    result = []

    def bullish(bar) -> bool:
        return bool(bar["close"] > bar["open"])

    def body(bar) -> float:
        return abs(bar["close"] - bar["open"])

    previous, current = bars.iloc[-2], bars.iloc[-1]
    timestamp = _timestamp(bars.index[-1])
    if bullish(current) and not bullish(previous) and current["open"] <= previous["close"] and current["close"] >= previous["open"]:
        result.append({"name": "bullish_engulfing", "timestamp": timestamp, "strict_match": True, "confirmation_next_bar": False})
    elif not bullish(current) and bullish(previous) and current["open"] >= previous["close"] and current["close"] <= previous["open"]:
        result.append({"name": "bearish_engulfing", "timestamp": timestamp, "strict_match": True, "confirmation_next_bar": False})
    elif body(current) < body(previous) and current["high"] <= previous["high"] and current["low"] >= previous["low"]:
        result.append({"name": "bullish_harami" if not bullish(previous) else "bearish_harami", "timestamp": timestamp, "strict_match": True, "confirmation_next_bar": False})

    if len(bars) < 3:
        return result
    first, middle, last = bars.iloc[0], bars.iloc[1], bars.iloc[2]
    midpoint = (first["open"] + first["close"]) / 2
    if not bullish(first) and body(middle) <= body(first) * 0.4 and bullish(last) and last["close"] > midpoint:
        result.append({"name": "morning_star", "timestamp": timestamp, "strict_match": True, "confirmation_next_bar": False})
    elif bullish(first) and body(middle) <= body(first) * 0.4 and not bullish(last) and last["close"] < midpoint:
        result.append({"name": "evening_star", "timestamp": timestamp, "strict_match": True, "confirmation_next_bar": False})
    elif all(bullish(bar) for _, bar in bars.iterrows()) and all(bars.iloc[i]["close"] > bars.iloc[i - 1]["close"] for i in (1, 2)):
        result.append({"name": "three_white_soldiers", "timestamp": timestamp, "strict_match": True, "confirmation_next_bar": False})
    elif all(not bullish(bar) for _, bar in bars.iterrows()) and all(bars.iloc[i]["close"] < bars.iloc[i - 1]["close"] for i in (1, 2)):
        result.append({"name": "three_black_crows", "timestamp": timestamp, "strict_match": True, "confirmation_next_bar": False})
    return result


def _major_patterns(high: pd.Series, low: pd.Series, close: pd.Series, interval: str) -> list[dict]:
    if interval in _MINUTE_KLT_MAP or len(close) < 15:
        return []
    sample_close = close.tail(60)
    sample_high = high.reindex(sample_close.index)
    sample_low = low.reindex(sample_close.index)
    patterns = []

    for kind, name, series, source_field in (("low", "double_bottom", sample_low, "low"), ("high", "double_top", sample_high, "high")):
        pivots = _pivot_positions(series, kind)
        if len(pivots) < 2:
            continue
        a, b = pivots[-2:]
        first, second = series.iloc[a], series.iloc[b]
        tolerance = max(abs(first) * 0.03, 0.01)
        if abs(first - second) > tolerance or b - a < 3:
            continue
        between = sample_close.iloc[a:b + 1]
        neckline = between.max() if kind == "low" else between.min()
        latest = sample_close.iloc[-1]
        confirmed = bool(latest > neckline) if kind == "low" else bool(latest < neckline)
        invalidated = bool(latest < min(first, second)) if kind == "low" else bool(latest > max(first, second))
        status = "invalidated" if invalidated else ("confirmed" if confirmed else "candidate")
        patterns.append({
            "name": name,
            "pivot_type": kind,
            "status": status,
            "confidence": "moderate" if b - a >= 5 else "low",
            "key_points": [
                {"timestamp": _timestamp(series.index[a]), "price": _number(first), "source_field": source_field},
                {"timestamp": _timestamp(series.index[b]), "price": _number(second), "source_field": source_field},
            ],
            "neckline": _number(neckline),
            "confirmation_rule": "close above neckline" if kind == "low" else "close below neckline",
            "invalidation_level": _number(min(first, second) if kind == "low" else max(first, second)),
        })
    return patterns


def _build_hist_analysis(df: pd.DataFrame, interval: str, source_last_trading_day: pd.Timestamp | None = None) -> dict:
    """Build compact, latest-state technical analysis without duplicating K-line rows."""
    latest_timestamp = df.index[-1] if not df.empty else None
    latest_date = latest_timestamp.date() if isinstance(latest_timestamp, pd.Timestamp) else None
    source_date = source_last_trading_day.date() if isinstance(source_last_trading_day, pd.Timestamp) else latest_date
    today = datetime.now().date()
    partial = interval in _MINUTE_KLT_MAP or (latest_date is not None and latest_date >= today)
    analysis = {
        "analysis_schema_version": 1,
        "interval": interval,
        "total_bars": len(df),
        "bar_status": "intraday_partial" if partial else "closed",
        "latest_bar_timestamp": latest_timestamp.strftime("%Y-%m-%d %H:%M") if interval in _MINUTE_KLT_MAP and isinstance(latest_timestamp, pd.Timestamp) else (latest_timestamp.strftime("%Y-%m-%d") if isinstance(latest_timestamp, pd.Timestamp) else None),
        "bar_period_end": latest_timestamp.strftime("%Y-%m-%d") if isinstance(latest_timestamp, pd.Timestamp) and interval not in _MINUTE_KLT_MAP else None,
        "source_last_trading_day": source_date.strftime("%Y-%m-%d") if source_date else None,
        "price_adjustment": "qfq",
    }
    if df.empty:
        analysis["summary"] = {"mechanical_score": None, "verdict": "insufficient_data", "signals": [], "correlated_signal_warning": False}
        return analysis

    close = pd.to_numeric(df["close"], errors="coerce")
    high = pd.to_numeric(df["high"], errors="coerce")
    low = pd.to_numeric(df["low"], errors="coerce")
    volume = pd.to_numeric(df["volume"], errors="coerce")
    windows = [5, 10, 20] if interval in _MINUTE_KLT_MAP else ([5] if interval in ("year", "yearly") else ([5, 10, 20] if interval in ("month", "monthly") else ([5, 10, 20, 60] if interval in ("week", "weekly") else [5, 10, 20, 60, 120])))
    mas = {window: close.rolling(window).mean() for window in windows}
    ma_values = {f"ma{window}": _number(series.iloc[-1]) for window, series in mas.items()}
    available_mas = [(window, series.iloc[-1]) for window, series in mas.items() if pd.notna(series.iloc[-1])]
    if len(available_mas) >= 2:
        ordered = all(available_mas[i][1] > available_mas[i + 1][1] for i in range(len(available_mas) - 1))
        reverse = all(available_mas[i][1] < available_mas[i + 1][1] for i in range(len(available_mas) - 1))
        arrangement = "bullish" if ordered else ("bearish" if reverse else "mixed")
    else:
        arrangement = None
    price_vs_ma = {f"ma{window}": ("above" if close.iloc[-1] > value else "below") for window, value in available_mas}
    crosses = {}
    for fast, slow in ((5, 10), (10, 20)):
        if fast in mas and slow in mas:
            crosses[f"ma{fast}_ma{slow}"] = _latest_cross(mas[fast], mas[slow])
    analysis["ma"] = {"values": ma_values, "arrangement": arrangement, "price_vs_ma": price_vs_ma, "crosses": crosses}

    macd = _get_macd(close) if len(close) >= 26 else None
    macd_cross = _latest_cross(macd["DIF"], macd["DEA"]) if macd is not None else None
    bars = macd["MACD_bar"].dropna() if macd is not None else pd.Series(dtype=float)
    if len(bars) >= 3:
        absolute = bars.iloc[-3:].abs().tolist()
        bar_direction = "expanding" if absolute[2] > absolute[1] > absolute[0] else ("shrinking" if absolute[2] < absolute[1] < absolute[0] else "stable")
    else:
        bar_direction = None
    analysis["macd"] = {"dif": _number(macd["DIF"].iloc[-1]) if macd is not None else None, "dea": _number(macd["DEA"].iloc[-1]) if macd is not None else None, "bar": _number(macd["MACD_bar"].iloc[-1]) if macd is not None else None, "cross": macd_cross["direction"] if macd_cross else None, "last_cross": macd_cross, "bar_direction": bar_direction}

    rsi = _get_rsi(close)["RSI"]
    rsi_value = _number(rsi.iloc[-1])
    rsi_delta = rsi.iloc[-1] - rsi.iloc[-5] if len(rsi) >= 5 and pd.notna(rsi.iloc[-1]) and pd.notna(rsi.iloc[-5]) else None
    analysis["rsi"] = {"value": rsi_value, "zone": "oversold" if rsi_value is not None and rsi_value < 30 else ("overbought" if rsi_value is not None and rsi_value > 70 else ("normal" if rsi_value is not None else None)), "direction": "up" if rsi_delta is not None and rsi_delta > 3 else ("down" if rsi_delta is not None and rsi_delta < -3 else ("flat" if rsi_delta is not None else None))}

    kdj = _get_stoch(high, low, close)
    j_value = _number(kdj["J"].iloc[-1])
    kdj_cross = _latest_cross(kdj["K"], kdj["D"])
    analysis["kdj"] = {"k": _number(kdj["K"].iloc[-1]), "d": _number(kdj["D"].iloc[-1]), "j": j_value, "zone": "oversold" if j_value is not None and j_value < 0 else ("overbought" if j_value is not None and j_value > 100 else ("normal" if j_value is not None else None)), "cross": kdj_cross["direction"] if kdj_cross else None, "last_cross": kdj_cross}

    boll = _get_bollinger_bands(close)
    upper, mid, lower = (boll[column].iloc[-1] for column in ("BOLL_upper", "BOLL_mid", "BOLL_lower"))
    if pd.isna(upper) or pd.isna(mid) or pd.isna(lower):
        position = bandwidth_trend = None
    else:
        position = "above_upper" if close.iloc[-1] > upper else ("upper_mid" if close.iloc[-1] >= mid else ("lower_mid" if close.iloc[-1] >= lower else "below_lower"))
        bandwidth = (boll["BOLL_upper"] - boll["BOLL_lower"]) / boll["BOLL_mid"].replace(0, np.nan)
        if len(bandwidth.dropna()) >= 2:
            change = bandwidth.iloc[-1] / bandwidth.iloc[-2] - 1
            bandwidth_trend = "expanding" if change > 0.02 else ("narrowing" if change < -0.02 else "stable")
        else:
            bandwidth_trend = None
    analysis["bollinger"] = {"upper": _number(upper), "mid": _number(mid), "lower": _number(lower), "position": position, "bandwidth_trend": bandwidth_trend}

    volume_ma5, volume_ma10 = volume.rolling(5).mean(), volume.rolling(10).mean()
    if len(df) >= 2 and pd.notna(volume.iloc[-1]) and pd.notna(volume.iloc[-2]):
        price_up, volume_up = close.iloc[-1] >= close.iloc[-2], volume.iloc[-1] >= volume.iloc[-2]
        price_volume = "healthy" if price_up and volume_up else ("divergence_up" if price_up else ("selling" if volume_up else "relief"))
    else:
        price_volume = None
    analysis["volume"] = {"ma5": _number(volume_ma5.iloc[-1]), "ma10": _number(volume_ma10.iloc[-1]), "latest": _number(volume.iloc[-1]), "price_volume": price_volume}
    analysis["trend"] = _trend_analysis(close, interval)
    analysis["macd"]["divergence"] = _macd_divergence(close, macd["DIF"] if macd is not None else pd.Series(dtype=float), interval)
    analysis["support_resistance"] = _support_resistance(high, low, close, interval)
    analysis["patterns"] = {
        "single_patterns": _single_patterns(df, interval),
        "multi_patterns": _multi_patterns(df, interval),
        "major_patterns": _major_patterns(high, low, close, interval),
    }

    signals = []
    if arrangement == "bullish":
        signals.append({"source": "trend", "signal": "bullish_ma_arrangement", "weight": 2, "evidence": price_vs_ma})
    elif arrangement == "bearish":
        signals.append({"source": "trend", "signal": "bearish_ma_arrangement", "weight": -2, "evidence": price_vs_ma})
    if macd_cross:
        signals.append({"source": "momentum", "signal": f"macd_{macd_cross['direction']}_cross", "weight": 1 if macd_cross["direction"] == "golden" else -1, "evidence": macd_cross})
    if rsi_value is not None and (rsi_value < 30 or rsi_value > 70):
        signals.append({"source": "oscillator", "signal": f"rsi_{'oversold' if rsi_value < 30 else 'overbought'}", "weight": 1 if rsi_value < 30 else -1, "evidence": {"value": rsi_value}})
    if price_volume == "healthy":
        signals.append({"source": "volume", "signal": "price_up_volume_up", "weight": 1, "evidence": {"relation": price_volume}})
    elif price_volume == "selling":
        signals.append({"source": "volume", "signal": "price_down_volume_up", "weight": -1, "evidence": {"relation": price_volume}})
    score = max(-6, min(6, sum(signal["weight"] for signal in signals)))
    verdict = "strong_bullish" if score >= 4 else ("bullish" if score >= 2 else ("strong_bearish" if score <= -4 else ("bearish" if score <= -2 else "neutral")))
    analysis["summary"] = {"mechanical_score": score, "verdict": verdict, "signals": signals, "correlated_signal_warning": len([s for s in signals if s["source"] == "trend"]) > 1}
    return analysis


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

            if interval in _MINUTE_KLT_MAP:
                df = _fetch_minute_kline(symbol)
                if df.empty:
                    return {"feature": feature, "data": None, "error": True, "error_reason": "No minute data available"}
                df = df.set_index("timestamp")
                source_last_trading_day = df.index[-1]
                ts_format = "%Y-%m-%d %H:%M"
            else:
                df = ak.stock_zh_a_daily(symbol=f"{exchange}{symbol}", adjust="qfq")
                df = df.rename(columns={"date": "timestamp"})
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                df["volume"] = df["volume"].astype("int64")
                df = df[["timestamp", "open", "high", "low", "close", "volume"]].set_index("timestamp")
                source_last_trading_day = df.index[-1]
                ts_format = "%Y-%m-%d"

                if interval != "day":
                    rule_map = {"week": "W", "month": "ME", "year": "YE", "weekly": "W", "monthly": "ME", "yearly": "YE"}
                    freq = rule_map.get(interval, "W")
                    df = df.resample(freq).agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()

            if interval == "day":
                recent_n = kwargs.get("hist_day_n", 120)
                if recent_n is not None:
                    df = df.tail(recent_n)
            elif interval in ("week", "weekly"):
                recent_n = kwargs.get("hist_week_n", 52)
                if recent_n is not None:
                    df = df.tail(recent_n)
            elif interval in ("month", "monthly"):
                recent_n = kwargs.get("hist_month_n", 36)
                if recent_n is not None:
                    df = df.tail(recent_n)
            elif interval in ("year", "yearly"):
                recent_n = kwargs.get("hist_year_n", 10)
                if recent_n is not None:
                    df = df.tail(recent_n)

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

            analysis = _build_hist_analysis(df, interval, source_last_trading_day) if kwargs.get("hist_analysis") else None
            df = df.reset_index()
            df["timestamp"] = df["timestamp"].dt.strftime(ts_format)
            raw = _df_to_list(df)
            raw_n = kwargs.get("hist_raw_n")
            if analysis is not None and raw_n is not None:
                raw = raw[-max(0, raw_n):] if raw_n else []
            data = {"raw": raw, "analysis": analysis} if analysis is not None else raw
            return {"feature": feature, "data": data, "error": False, "error_reason": None}

        elif feature == "realtime":
            return _tencent_realtime(symbol)

        elif feature == "fund_flow":
            exchange = "1" if _exchange_lower(symbol) == "sh" else "0"
            records = []

            try:
                # push2delay: today's full breakdown (主力/超大单/大单/中单/小单)
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

                # f178: historical trend (主力净流入 only, last 5 days)
                url2 = "https://29.push2delay.eastmoney.com/api/qt/stock/get"
                params2 = {"secid": f"{exchange}.{symbol}", "ut": "bd1d9ddb04089700cf9c27f6f7426281", "fltt": "2", "invt": "2", "fields": "f57,f58,f178"}
                resp2 = _session.get(url2, params=params2, timeout=5)
                data2 = resp2.json()
                if data2.get("data") and data2["data"].get("f178"):
                    hist = json.loads(data2["data"]["f178"]) if isinstance(data2["data"]["f178"], str) else data2["data"]["f178"]
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
            if "交易日" in df.columns:
                df["交易日"] = df["交易日"].astype(str)
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

        elif feature == "restricted_release":
            df = ak.stock_restricted_release_queue_em(symbol=symbol)
            if "解禁时间" in df.columns:
                today = datetime.now().date()
                future = df["解禁时间"].apply(lambda x: x > today if pd.notna(x) else False)
                for col in ["解禁前一交易日收盘价", "解禁前20日涨跌幅", "解禁后20日涨跌幅"]:
                    if col in df.columns:
                        df.loc[future, col] = None

                # Cross-reference with additional_issuance to compute cost basis
                cost_map = {}
                try:
                    iss_df = ak.stock_add_stock(symbol=symbol)
                    if not iss_df.empty and "公告日期" in iss_df.columns and "发行价格" in iss_df.columns:
                        iss_df = iss_df.copy()
                        iss_df["公告日期"] = pd.to_datetime(iss_df["公告日期"], errors="coerce")
                        iss_df["发行价格_数值"] = iss_df["发行价格"].str.extract(r"([\d.]+)").astype(float)
                        for _, rel_row in df.iterrows():
                            rel_date = rel_row["解禁时间"]
                            if pd.notna(rel_date):
                                best_match = None
                                best_score = 999
                                for _, iss_row in iss_df.iterrows():
                                    iss_date = iss_row["公告日期"]
                                    if pd.notna(iss_date) and iss_date < pd.Timestamp(rel_date):
                                        months = (pd.Timestamp(rel_date) - iss_date).days / 30.44
                                        score = min(abs(months - 6), abs(months - 36))
                                        if score < best_score:
                                            best_score = score
                                            best_match = iss_row
                                if best_match is not None and best_score < 6:
                                    cost_map[rel_date] = best_match["发行价格_数值"]
                except Exception:
                    pass

                df["参考增发价"] = df["解禁时间"].map(cost_map)
                df["解禁时间"] = df["解禁时间"].apply(lambda x: x.strftime("%Y-%m-%d") if pd.notna(x) else None)
            return {"feature": feature, "data": _df_to_list(df), "error": False, "error_reason": None}

        elif feature == "additional_issuance":
            df = ak.stock_add_stock(symbol=symbol)
            if "公告日期" in df.columns:
                df["公告日期"] = df["公告日期"].apply(lambda x: x.strftime("%Y-%m-%d") if pd.notna(x) else None)
            return {"feature": feature, "data": _df_to_list(df), "error": False, "error_reason": None}

        elif feature == "block_trade":
            end = _last_trading_day()
            start_date = datetime.now() - pd.Timedelta(days=30)
            start = _last_trading_day(start_date.date())
            df = ak.stock_dzjy_mrmx(symbol="A股", start_date=start, end_date=end)
            df = df[df["证券代码"].astype(str) == symbol]
            n = kwargs.get("recent_n", 10)
            if n is not None:
                df = df.head(n)
            return {"feature": feature, "data": _df_to_list(df), "error": False, "error_reason": None}

        elif feature == "margin_trade":
            exchange = _exchange_lower(symbol)
            dates = []
            target = datetime.now().date()
            for _ in range(10):
                td = _last_trading_day(target)
                if td not in dates:
                    dates.append(td)
                target -= pd.Timedelta(days=1)
                if len(dates) >= 3:
                    break

            def _fetch_one(trade_date: str) -> dict | None:
                try:
                    if exchange in ("sh",):
                        resp = _session.get("https://query.sse.com.cn/marketdata/tradedata/queryMargin.do", params={
                            "isPagination": "true", "tabType": "mxtype", "detailsDate": trade_date,
                            "stockCode": symbol, "pageHelp.pageSize": "10", "pageHelp.pageNo": "1",
                        }, headers={"Referer": "https://www.sse.com.cn/"}, timeout=10)
                        for rec in (resp.json().get("result") or []):
                            return {
                                "信用交易日期": rec["opDate"][:4] + "-" + rec["opDate"][4:6] + "-" + rec["opDate"][6:8],
                                "证券代码": rec["stockCode"], "证券简称": rec["securityAbbr"],
                                "融资余额": rec.get("rzye"), "融资买入额": rec.get("rzmre"),
                                "融资偿还额": rec.get("rzche"), "融券余量": rec.get("rqyl"),
                                "融券卖出量": rec.get("rqmcl"), "融券偿还量": rec.get("rqchl"),
                            }
                    elif exchange in ("sz",):
                        df = ak.stock_margin_detail_szse(date=trade_date)
                        if not df.empty:
                            matched = df[df["证券代码"].astype(str) == symbol]
                            if not matched.empty:
                                rec = matched.iloc[0].to_dict()
                                rec["信用交易日期"] = trade_date[:4] + "-" + trade_date[4:6] + "-" + trade_date[6:8]
                                return rec
                except Exception:
                    pass
                return None

            rows = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(dates)) as pool:
                for result in pool.map(_fetch_one, dates):
                    if result:
                        rows.append(result)
            rows.sort(key=lambda r: r.get("信用交易日期", ""), reverse=True)
            return {"feature": feature, "data": rows, "error": False, "error_reason": None}

        elif feature == "shareholder_count":
            params = {
                "sortColumns": "HOLD_NOTICE_DATE,SECURITY_CODE",
                "sortTypes": "-1,-1",
                "pageSize": "500",
                "pageNumber": "1",
                "reportName": "RPT_HOLDERNUMLATEST",
                "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,END_DATE,INTERVAL_CHRATE,AVG_MARKET_CAP,AVG_HOLD_NUM,TOTAL_MARKET_CAP,TOTAL_A_SHARES,HOLD_NOTICE_DATE,HOLDER_NUM,PRE_HOLDER_NUM,HOLDER_NUM_CHANGE,HOLDER_NUM_RATIO,PRE_END_DATE",
                "filter": f'(SECURITY_CODE="{symbol}")',
                "quoteColumns": "f2,f3",
                "source": "WEB",
                "client": "WEB",
            }
            r = _session.get("https://datacenter-web.eastmoney.com/api/data/v1/get", params=params, timeout=10)
            data = r.json()
            recs = (data.get("result") or {}).get("data") or []
            _map = {
                "SECURITY_CODE": "股票代码", "SECURITY_NAME_ABBR": "股票简称",
                "END_DATE": "统计截止日期", "INTERVAL_CHRATE": "区间涨跌幅",
                "AVG_MARKET_CAP": "户均持股市值", "AVG_HOLD_NUM": "户均持股数",
                "TOTAL_MARKET_CAP": "总市值", "TOTAL_A_SHARES": "总股本",
                "HOLD_NOTICE_DATE": "公告日期", "HOLDER_NUM": "股东户数",
                "PRE_HOLDER_NUM": "上期股东户数", "HOLDER_NUM_CHANGE": "股东户数变化",
                "HOLDER_NUM_RATIO": "股东户数变化率", "PRE_END_DATE": "上期截止日期",
                "f2": "最新收盘价", "f3": "最新涨跌幅",
            }
            recs = [{_map.get(k, k): v for k, v in r.items()} for r in recs]
            for r in recs:
                for k in list(r.keys()):
                    if isinstance(r[k], str) and r[k].endswith(" 00:00:00"):
                        r[k] = r[k][:10]
            return {"feature": feature, "data": recs, "error": False, "error_reason": None}

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
    features: Annotated[list[str], "REQUIRED: ALL features needed in ONE call. DO NOT make multiple get_data calls — batch everything here. Supported: news, inner_trade, financial, fund_flow, concept, hsgt_summary, hist_data, realtime, time_info, restricted_release, additional_issuance, block_trade, margin_trade, shareholder_count"],
    news_recent_n: Annotated[int | None, "Number of most recent news records"] = 10,
    recent_n: Annotated[int | None, "Number of most recent financial statement / block_trade records"] = 10,
    hist_interval: Annotated[str, "K-line interval for hist_data (1min/day/week/month/year)"] = "day",
    hist_indicators: Annotated[list[str] | None, "Technical indicators for hist_data (e.g. KDJ, MACD, RSI, BOLL, SMA)"] = ["KDJ","MACD","RSI","BOLL","SMA"],
    hist_day_n: Annotated[int | None, "日K返回条数（默认120）"] = 120,
    hist_week_n: Annotated[int | None, "周K返回条数（默认52）"] = 52,
    hist_month_n: Annotated[int | None, "月K返回条数（默认36，不传则全返回）"] = 36,
    hist_year_n: Annotated[int | None, "年K返回条数（默认10，不传则全返回）"] = 10,
    hist_analysis: Annotated[bool, "Return compact P0 technical analysis with hist_data; defaults to false for response compatibility"] = False,
    hist_raw_n: Annotated[int | None, "With hist_analysis=true, limit raw K-line rows; 0 returns analysis only, null preserves all raw rows"] = None,
) -> str:
    """SINGLE-CALL batch stock data fetcher. Returns JSON array with ALL requested features' data in one response.

    Logs call details to stderr for debugging.

    ⚠️ CRITICAL: Pass ALL desired features in 'features' list at once. Multiple get_data calls for the same symbol are wasteful and prohibited — this tool is designed for batch querying.

    Each result entry has: {feature, data, error, error_reason}.

    Example:
      get_data(symbol="000625", features=["news", "inner_trade", "financial", "fund_flow", "concept", "hsgt_summary"], news_recent_n=10, recent_n=3)
      get_data(symbol="000625", features=["hist_data"], hist_indicators=["KDJ","MACD","RSI","BOLL","SMA"])
      get_data(symbol="000625", features=["hist_data"], hist_analysis=true)
      get_data(symbol="000625", features=["hist_data"], hist_analysis=true, hist_raw_n=10)
      get_data(symbol="000625", features=["hist_data"], hist_interval="week", hist_week_n=52)
      get_data(symbol="000625", features=["hist_data"], hist_interval="month", hist_month_n=36, hist_indicators=["KDJ","MACD","RSI","BOLL","SMA"])
      get_data(symbol="000625", features=["hist_data"], hist_interval="year", hist_year_n=10, hist_indicators=["KDJ","MACD","RSI","BOLL","SMA"])
      get_data(symbol="600733", features=["block_trade", "margin_trade", "shareholder_count"], recent_n=10)
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] get_data called: symbol={symbol}, features={features}, news_recent_n={news_recent_n}, recent_n={recent_n}, hist_interval={hist_interval}, hist_indicators={hist_indicators}, hist_day_n={hist_day_n}, hist_week_n={hist_week_n}, hist_month_n={hist_month_n}, hist_year_n={hist_year_n}, hist_analysis={hist_analysis}, hist_raw_n={hist_raw_n}", file=sys.stderr, flush=True)
    kwargs = {
        "news_recent_n": news_recent_n,
        "recent_n": recent_n,
        "hist_interval": hist_interval,
        "hist_indicators": hist_indicators or [],
        "hist_day_n": hist_day_n,
        "hist_week_n": hist_week_n,
        "hist_month_n": hist_month_n,
        "hist_year_n": hist_year_n,
        "hist_analysis": hist_analysis,
        "hist_raw_n": hist_raw_n,
    }
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(features)) as pool:
        futures = {pool.submit(_call_feature, f, symbol, kwargs): f for f in features}
        done, _ = concurrent.futures.wait(futures, timeout=60)
        for f in futures:
            if f not in done:
                f.cancel()
        results = []
        for f in concurrent.futures.as_completed(list(done)):
            try:
                results.append(f.result(timeout=5))
            except Exception as e:
                feature_name = futures.get(f, "unknown")
                results.append({"feature": feature_name, "data": None, "error": True, "error_reason": f"Timeout: {e}"})
    payload = json.dumps(results, ensure_ascii=False)
    for r in results:
        data_len = len(json.dumps(r.get("data", ""), ensure_ascii=False)) if r.get("data") else 0
        print(f"  [{r.get('feature')}] error={r.get('error')}, data_chars={data_len}", file=sys.stderr, flush=True)
    print(f"  total={len(payload)} chars", file=sys.stderr, flush=True)
    return payload
