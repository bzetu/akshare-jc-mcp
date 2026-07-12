import akshare as ak
import time

# Try stock_zh_a_spot (not _em)
t0 = time.time()
try:
    df = ak.stock_zh_a_spot()
    print(f'stock_zh_a_spot: OK ({time.time()-t0:.1f}s) shape={df.shape}')
    print(df.columns.tolist()[:10])
    # Filter for our symbol
    sub = df[df['代码'] == '600733']
    print(f'filtered: {sub.shape}')
    if len(sub) > 0:
        print(sub.to_dict(orient='records')[0])
except Exception as e:
    print(f'stock_zh_a_spot: {type(e).__name__}: {e}')
