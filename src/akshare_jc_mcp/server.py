import json
import traceback
from datetime import datetime
from typing import Annotated, Literal

import akshare as ak
import akshare_one as ako
from akshare_one import indicators
from fastmcp import FastMCP

mcp = FastMCP(name="akshare-jc-mcp")

_HIST_INDICATOR_MAP = {
    "SMA": (indicators.get_sma, {"window": 20}),
    "EMA": (indicators.get_ema, {"window": 20}),
    "RSI": (indicators.get_rsi, {"window": 14}),
    "MACD": (indicators.get_macd, {"fast": 12, "slow": 26, "signal": 9}),
    "BOLL": (indicators.get_bollinger_bands, {"window": 20, "std": 2}),
    "KDJ": (indicators.get_stoch, {"window": 14, "smooth_d": 3, "smooth_k": 3}),
    "ATR": (indicators.get_atr, {"window": 14}),
    "CCI": (indicators.get_cci, {"window": 14}),
    "ADX": (indicators.get_adx, {"window": 14}),
    "WILLR": (indicators.get_willr, {"window": 14}),
    "AD": (indicators.get_ad, {}),
    "ADOSC": (indicators.get_adosc, {"fast_period": 3, "slow_period": 10}),
    "OBV": (indicators.get_obv, {}),
    "MOM": (indicators.get_mom, {"window": 10}),
    "SAR": (indicators.get_sar, {"acceleration": 0.02, "maximum": 0.2}),
    "TSF": (indicators.get_tsf, {"window": 14}),
    "APO": (indicators.get_apo, {"fast_period": 12, "slow_period": 26, "ma_type": 0}),
    "AROON": (indicators.get_aroon, {"window": 14}),
    "AROONOSC": (indicators.get_aroonosc, {"window": 14}),
    "BOP": (indicators.get_bop, {}),
    "CMO": (indicators.get_cmo, {"window": 14}),
    "DX": (indicators.get_dx, {"window": 14}),
    "MFI": (indicators.get_mfi, {"window": 14}),
    "MINUS_DI": (indicators.get_minus_di, {"window": 14}),
    "MINUS_DM": (indicators.get_minus_dm, {"window": 14}),
    "PLUS_DI": (indicators.get_plus_di, {"window": 14}),
    "PLUS_DM": (indicators.get_plus_dm, {"window": 14}),
    "PPO": (indicators.get_ppo, {"fast_period": 12, "slow_period": 26, "ma_type": 0}),
    "ROC": (indicators.get_roc, {"window": 10}),
    "ROCP": (indicators.get_rocp, {"window": 10}),
    "ROCR": (indicators.get_rocr, {"window": 10}),
    "ROCR100": (indicators.get_rocr100, {"window": 10}),
    "TRIX": (indicators.get_trix, {"window": 30}),
    "ULTOSC": (indicators.get_ultosc, {"window1": 7, "window2": 14, "window3": 28}),
}


def _call_feature(feature: str, symbol: str, kwargs: dict) -> dict:
    try:
        if feature == "news":
            df = ako.get_news_data(symbol=symbol, source="eastmoney")
            if kwargs.get("recent_n") is not None:
                df = df.tail(kwargs["recent_n"])
            return {"feature": feature, "data": df.to_json(orient="records"), "error": False, "error_reason": None}

        elif feature == "inner_trade":
            df = ako.get_inner_trade_data(symbol, source="xueqiu")
            return {"feature": feature, "data": df.to_json(orient="records"), "error": False, "error_reason": None}

        elif feature == "financial":
            df = ako.get_financial_metrics(symbol)
            if kwargs.get("recent_n") is not None:
                df = df.head(kwargs["recent_n"])
            return {"feature": feature, "data": df.to_json(orient="records"), "error": False, "error_reason": None}

        elif feature == "balance_sheet":
            df = ako.get_balance_sheet(symbol=symbol, source="sina")
            if kwargs.get("recent_n") is not None:
                df = df.head(kwargs["recent_n"])
            return {"feature": feature, "data": df.to_json(orient="records"), "error": False, "error_reason": None}

        elif feature == "income_statement":
            df = ako.get_income_statement(symbol=symbol, source="sina")
            if kwargs.get("recent_n") is not None:
                df = df.head(kwargs["recent_n"])
            return {"feature": feature, "data": df.to_json(orient="records"), "error": False, "error_reason": None}

        elif feature == "cash_flow":
            df = ako.get_cash_flow(symbol=symbol, source="sina")
            if kwargs.get("recent_n") is not None:
                df = df.head(kwargs["recent_n"])
            return {"feature": feature, "data": df.to_json(orient="records"), "error": False, "error_reason": None}

        elif feature == "hist_data":
            df = ako.get_hist_data(
                symbol=symbol,
                interval=kwargs.get("hist_interval", "day"),
                source="sina",
            )
            indicators_list = kwargs.get("hist_indicators") or []
            if indicators_list:
                temp = []
                for ind in indicators_list:
                    if ind.upper() in _HIST_INDICATOR_MAP:
                        func, params = _HIST_INDICATOR_MAP[ind.upper()]
                        indicator_df = func(df, **params)
                        temp.append(indicator_df)
                if temp:
                    df = df.join(temp)
            recent_n = kwargs.get("hist_recent_n", 120)
            if recent_n is not None:
                df = df.tail(recent_n)
            return {"feature": feature, "data": df.to_json(orient="records"), "error": False, "error_reason": None}

        elif feature == "realtime":
            df = ako.get_realtime_data(symbol=symbol, source="eastmoney_direct")
            return {"feature": feature, "data": df.to_json(orient="records"), "error": False, "error_reason": None}

        elif feature == "time_info":
            local_time = datetime.now().astimezone()
            current_date = local_time.date()
            trade_date_df = ak.tool_trade_date_hist_sina()
            trade_dates = [d for d in trade_date_df["trade_date"]]
            past_dates = sorted([d for d in trade_dates if d <= current_date], reverse=True)
            last_trading_day = past_dates[0].strftime("%Y-%m-%d") if past_dates else None
            return {
                "feature": feature,
                "data": json.dumps({
                    "iso_format": local_time.isoformat(),
                    "timestamp": local_time.timestamp(),
                    "last_trading_day": last_trading_day,
                }),
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
    features: Annotated[list[str], "List of data features to fetch. Supported: news, inner_trade, financial, balance_sheet, income_statement, cash_flow, hist_data, realtime, time_info"],
    hist_interval: Annotated[str, "K-line interval for hist_data (minute/hour/day/week/month/year)"] = "day",
    hist_indicators: Annotated[list[str] | None, "Technical indicators for hist_data (e.g. KDJ, MACD, RSI, BOLL, SMA)"] = None,
    hist_recent_n: Annotated[int | None, "Number of most recent hist_data records"] = 120,
    recent_n: Annotated[int | None, "Number of most recent records for news/financial statements"] = 10,
) -> str:
    """Unified stock data fetcher. Calls all requested features and returns a JSON array.

    Each result entry has: {feature, data, error, error_reason}.

    Example:
      get_data(symbol="000625", features=["news", "inner_trade", "financial"])
      get_data(symbol="000625", features=["hist_data"], hist_indicators=["KDJ","MACD","RSI","BOLL","SMA"])
    """
    kwargs = {
        "hist_interval": hist_interval,
        "hist_indicators": hist_indicators or [],
        "hist_recent_n": hist_recent_n,
        "recent_n": recent_n,
    }
    results = [_call_feature(f, symbol, kwargs) for f in features]
    return json.dumps(results, ensure_ascii=False)
