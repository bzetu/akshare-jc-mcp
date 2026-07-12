import akshare as ak
import time, inspect

# Check stock_financial_report_sina signature
sig = inspect.signature(ak.stock_financial_report_sina)
print(f'stock_financial_report_sina: {sig}')

# Check stock_zh_a_spot signature
sig = inspect.signature(ak.stock_zh_a_spot)
print(f'stock_zh_a_spot: {sig}')

# Try stock_zh_a_spot again with better error handling
t0 = time.time()
try:
    df = ak.stock_zh_a_spot()
    print(f'stock_zh_a_spot: OK ({time.time()-t0:.1f}s) shape={df.shape}')
    print(df.columns.tolist()[:15])
except Exception as e:
    print(f'stock_zh_a_spot: {type(e).__name__}: {e}')

# Try Sina-based financial reports
t0 = time.time()
try:
    df = ak.stock_financial_report_sina(stock='600733', symbol='资产负债表')
    print(f'balance_sheet sina: OK ({time.time()-t0:.1f}s) shape={df.shape}')
    print(df.columns.tolist()[:5])
except Exception as e:
    print(f'balance_sheet sina: {type(e).__name__}: {e}')

t0 = time.time()
try:
    df = ak.stock_financial_report_sina(stock='600733', symbol='利润表')
    print(f'income_statement sina: OK ({time.time()-t0:.1f}s) shape={df.shape}')
except Exception as e:
    print(f'income_statement sina: {type(e).__name__}: {e}')

t0 = time.time()
try:
    df = ak.stock_financial_report_sina(stock='600733', symbol='现金流量表')
    print(f'cash_flow sina: OK ({time.time()-t0:.1f}s) shape={df.shape}')
except Exception as e:
    print(f'cash_flow sina: {type(e).__name__}: {e}')
