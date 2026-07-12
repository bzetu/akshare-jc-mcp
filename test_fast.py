import akshare as ak
import time

# Try stock_zh_a_hist with only 1 day range - this should return 1 row fast
t0 = time.time()
try:
    df = ak.stock_zh_a_hist(symbol="600733", period="daily", start_date="20260701", adjust="qfq")
    print(f'stock_zh_a_hist: OK ({time.time()-t0:.1f}s) shape={df.shape}')
    print(df.columns.tolist())
    print(df.tail(1).to_dict(orient='records')[0])
except Exception as e:
    print(f'stock_zh_a_hist: {type(e).__name__}: {e}')

# Try stock_financial_report_sina for balance sheet
t0 = time.time()
try:
    df = ak.stock_financial_report_sina(stock='600733', symbol="资产负债表")
    print(f'stock_financial_report_sina: OK ({time.time()-t0:.1f}s) shape={df.shape}')
except Exception as e:
    print(f'stock_financial_report_sina: {type(e).__name__}: {e}')
