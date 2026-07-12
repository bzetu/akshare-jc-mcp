import sys, json, time
sys.path.insert(0, r'C:\Users\jiangcheng_m.CYOU-INC\Desktop\akshare-jc-mcp\src')
from akshare_jc_mcp.server import get_data

symbol = '600733'
features = ['news', 'inner_trade', 'financial', 'balance_sheet', 'income_statement', 'cash_flow', 'hist_data', 'realtime', 'time_info']

t0 = time.time()
result = json.loads(get_data(symbol=symbol, features=features))
total = time.time() - t0

for r in sorted(result, key=lambda x: x['feature']):
    status = 'OK' if not r['error'] else f"ERROR: {r['error_reason']}"
    print(f"{r['feature']}: {status}")

print(f'\nTotal time: {total:.1f}s (parallel)')
