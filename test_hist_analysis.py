import sys
import unittest

import numpy as np
import pandas as pd
from unittest.mock import patch

sys.path.insert(0, r"C:\Users\jiangcheng_m.CYOU-INC\Desktop\akshare-jc-mcp\src")

from akshare_jc_mcp.server import _build_hist_analysis, _call_feature


class HistAnalysisTest(unittest.TestCase):
    def test_daily_analysis_contains_compact_p0_results(self):
        index = pd.date_range("2025-01-01", periods=130, freq="B")
        close = pd.Series(np.linspace(10, 20, len(index)), index=index)
        df = pd.DataFrame({
            "open": close - 0.2,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.arange(1000, 1000 + len(index)),
        }, index=index)

        analysis = _build_hist_analysis(df, "day")

        self.assertEqual(analysis["analysis_schema_version"], 1)
        self.assertEqual(analysis["total_bars"], 130)
        self.assertEqual(set(analysis["ma"]["values"]), {"ma5", "ma10", "ma20", "ma60", "ma120"})
        self.assertIn(analysis["ma"]["arrangement"], {"bullish", "bearish", "mixed"})
        self.assertIn("last_cross", analysis["macd"])
        self.assertIn("zone", analysis["rsi"])
        self.assertIn("zone", analysis["kdj"])
        self.assertIn("position", analysis["bollinger"])
        self.assertIn("mechanical_score", analysis["summary"])
        self.assertIn("direction", analysis["trend"])
        self.assertIn("divergence", analysis["macd"])
        self.assertIn("support_levels", analysis["support_resistance"])
        self.assertIn("single_patterns", analysis["patterns"])
        self.assertIn("multi_patterns", analysis["patterns"])
        self.assertIn("major_patterns", analysis["patterns"])

    def test_short_series_is_null_safe(self):
        index = pd.date_range("2025-01-01", periods=3, freq="B")
        df = pd.DataFrame({
            "open": [10, 11, 12], "high": [11, 12, 13], "low": [9, 10, 11],
            "close": [10, 11, 12], "volume": [100, 200, 300],
        }, index=index)

        analysis = _build_hist_analysis(df, "day")

        self.assertIsNone(analysis["rsi"]["value"])
        self.assertIsNone(analysis["kdj"]["k"])
        self.assertIsNone(analysis["bollinger"]["position"])
        self.assertEqual(analysis["summary"]["mechanical_score"], 1)

    def test_minute_series_uses_minute_windows_and_partial_status(self):
        index = pd.date_range("2025-01-01 09:30", periods=30, freq="min")
        close = pd.Series(np.linspace(10, 12, len(index)), index=index)
        df = pd.DataFrame({
            "open": close - 0.1, "high": close + 0.2, "low": close - 0.2,
            "close": close, "volume": 100,
        }, index=index)

        analysis = _build_hist_analysis(df, "1min")

        self.assertEqual(analysis["bar_status"], "intraday_partial")
        self.assertEqual(set(analysis["ma"]["values"]), {"ma5", "ma10", "ma20"})
        self.assertEqual(analysis["support_resistance"], {"support_levels": [], "resistance_levels": []})
        self.assertEqual(analysis["patterns"]["single_patterns"], [])
        self.assertEqual(analysis["patterns"]["multi_patterns"], [])
        self.assertEqual(analysis["patterns"]["major_patterns"], [])
        self.assertFalse(analysis["macd"]["divergence"]["bullish"]["detected"])

    def test_detects_confirmed_double_bottom(self):
        close = [10, 9, 8, 9, 10, 9, 8.1, 9, 10.2, 11, 12, 13, 14, 15, 16]
        index = pd.date_range("2025-01-01", periods=len(close), freq="B")
        series = pd.Series(close, index=index)
        df = pd.DataFrame({
            "open": series - 0.1, "high": series + 0.2, "low": series - 0.2,
            "close": series, "volume": 100,
        }, index=index)

        analysis = _build_hist_analysis(df, "day")

        bottoms = [p for p in analysis["patterns"]["major_patterns"] if p["name"] == "double_bottom"]
        self.assertEqual(len(bottoms), 1)
        self.assertEqual(bottoms[0]["status"], "confirmed")
        self.assertEqual(bottoms[0]["pivot_type"], "low")
        self.assertTrue(all(point["source_field"] == "low" for point in bottoms[0]["key_points"]))

    def test_period_end_is_distinct_from_last_trading_day(self):
        index = pd.DatetimeIndex([pd.Timestamp("2026-06-30"), pd.Timestamp("2026-07-31")])
        df = pd.DataFrame({
            "open": [10, 11], "high": [11, 12], "low": [9, 10],
            "close": [10, 11], "volume": [100, 200],
        }, index=index)

        analysis = _build_hist_analysis(df, "month", pd.Timestamp("2026-07-17"))

        self.assertEqual(analysis["bar_period_end"], "2026-07-31")
        self.assertEqual(analysis["source_last_trading_day"], "2026-07-17")
        self.assertEqual(analysis["bar_status"], "intraday_partial")

    def test_double_top_uses_high_pivots(self):
        close = [10, 11, 12, 11, 10, 11, 11.9, 11, 10, 9, 8, 7, 6, 5, 4]
        index = pd.date_range("2025-01-01", periods=len(close), freq="B")
        series = pd.Series(close, index=index)
        df = pd.DataFrame({
            "open": series - 0.1, "high": series + 0.3, "low": series - 0.2,
            "close": series, "volume": 100,
        }, index=index)

        analysis = _build_hist_analysis(df, "day")

        tops = [p for p in analysis["patterns"]["major_patterns"] if p["name"] == "double_top"]
        self.assertEqual(len(tops), 1)
        self.assertEqual(tops[0]["status"], "confirmed")
        self.assertEqual(tops[0]["pivot_type"], "high")
        self.assertTrue(all(point["source_field"] == "high" for point in tops[0]["key_points"]))

    def test_hist_raw_n_limits_output_without_limiting_analysis(self):
        index = pd.date_range("2025-01-01", periods=30, freq="B")
        close = pd.Series(np.linspace(10, 15, len(index)), index=index)
        source = pd.DataFrame({
            "date": index, "open": close - 0.1, "high": close + 0.2,
            "low": close - 0.2, "close": close, "volume": 100,
        })
        kwargs = {"hist_interval": "day", "hist_day_n": 30, "hist_indicators": [], "hist_analysis": True, "hist_raw_n": 0}
        with patch("akshare_jc_mcp.server.ak.stock_zh_a_daily", return_value=source):
            result = _call_feature("hist_data", "600733", kwargs)

        self.assertEqual(result["data"]["raw"], [])
        self.assertEqual(result["data"]["analysis"]["total_bars"], 30)

        kwargs["hist_raw_n"] = 5
        with patch("akshare_jc_mcp.server.ak.stock_zh_a_daily", return_value=source):
            result = _call_feature("hist_data", "600733", kwargs)

        self.assertEqual(len(result["data"]["raw"]), 5)
        self.assertEqual(result["data"]["analysis"]["total_bars"], 30)


if __name__ == "__main__":
    unittest.main()
