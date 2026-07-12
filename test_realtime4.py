import akshare as ak
import time

# Try exchange-specific spot (only Shanghai stocks)
t0 = time.time()
try:
    df = ak.stock_sh_a_spot_em()
    print(f'stock_sh_a_spot_em: OK ({time.time()-t0:.1f}s) shape={df.shape}')
    print(df.columns.tolist())
    # Filter for our symbol
    sub = df[df['代码'] == '600733']
    print(f'filtered: {sub.shape}')
    if len(sub) > 0:
        print(sub.to_dict(orient='records')[0])
except Exception as e:
    print(f'stock_sh_a_spot_em: {type(e).__name__}: {e}')
