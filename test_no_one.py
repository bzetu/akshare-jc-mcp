import sys, json, time
sys.path.insert(0, r'C:\Users\jiangcheng_m.CYOU-INC\Desktop\akshare-jc-mcp\src')
from akshare_jc_mcp.server import get_data

symbol = '600733'
features = ['news', 'inner_trade', 'financial', 'balance_sheet', 'income_statement', 'cash_flow', 'realtime', 'time_info']

for f in features:
    t0 = time.time()
    try:
        result = json.loads(get_data(symbol=symbol, features=[f]))
        t = time.time() - t0
        r = result[0]
        status = 'OK' if not r['error'] else f"ERROR: {r['error_reason']}"
        print(f"{r['feature']}: {status} ({t:.1f}s)")
    except Exception as e:
        t = time.time() - t0
        print(f"{f}: CRASHED ({t:.1f}s): {e}")
