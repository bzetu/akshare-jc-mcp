import akshare as ak
import time

# Try stock_zh_a_hist for latest daily data (fast, single stock)
t0 = time.time()
try:
    df = ak.stock_zh_a_hist(symbol="600733", period="daily", start_date="20260701", end_date="20260707", adjust="qfq")
    print(f'stock_zh_a_hist: OK ({time.time()-t0:.1f}s) shape={df.shape}')
    print(df.columns.tolist())
    print(df.tail(1).to_dict(orient='records')[0])
except Exception as e:
    print(f'stock_zh_a_hist: {type(e).__name__}: {e}')

# Also try Sina realtime (fast single stock)
t0 = time.time()
try:
    df = ak.stock_zh_a_spot()
    # Find the column with code
    print(f'stock_zh_a_spot cols: {[c for c in df.columns]}')
    # Try filtering
    mask = df.apply(lambda row: '600733' in str(row.values), axis=1)
    print(f'matched rows: {mask.sum()}')
except Exception as e:
    print(f'stock_zh_a_spot: {type(e).__name__}: {e}')
