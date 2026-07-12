import sys, json
sys.path.insert(0, r'C:\Users\jiangcheng_m.CYOU-INC\Desktop\akshare-jc-mcp\src')
from akshare_jc_mcp.server import get_data

result = json.loads(get_data(symbol="600733", features=["hist_data"], hist_indicators=["KDJ","MACD","RSI","BOLL","SMA"]))
r = result[0]
print(f"hist_data: {'OK' if not r['error'] else r['error_reason']}")
if not r['error']:
    data = json.loads(r['data'])
    print(f"Records: {len(data)}")
    latest = data[-1]
    print(f"Latest: close={latest.get('close')}, KDJ_K={latest.get('K')}, MACD_DIF={latest.get('DIF')}, RSI={latest.get('RSI')}")
