import akshare as ak
import time

for sym in ['600733', 'SH600733']:
    t0 = time.time()
    try:
        df = ak.stock_individual_spot_xq(symbol=sym)
        print(f'{sym}: OK ({time.time()-t0:.1f}s) cols={df.columns.tolist()[:8]}')
    except Exception as e:
        print(f'{sym}: {type(e).__name__}: {e}')

t0 = time.time()
try:
    df = ak.stock_zh_a_tick_tx_js(symbol='sh600733')
    print(f'tick_tx: OK ({time.time()-t0:.1f}s) shape={df.shape}')
    print(df.columns.tolist()[:10])
except Exception as e:
    print(f'tick_tx: {type(e).__name__}: {e}')
