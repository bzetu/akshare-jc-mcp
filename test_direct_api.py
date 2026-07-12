import requests, time

# Direct eastmoney API for single stock realtime quote
# secid: 1=SH, 0=SZ
symbol = '600733'

t0 = time.time()
url = f'https://push2.eastmoney.com/api/qt/stock/get?secid=1.{symbol}&fields=f43,f44,f45,f46,f47,f48,f49,f50,f51,f52,f57,f58,f170'
try:
    resp = requests.get(url, timeout=10)
    print(f'direct eastmoney: OK ({time.time()-t0:.1f}s) status={resp.status_code}')
    print(resp.json()['data'][:5]) if resp.ok else print(resp.text[:200])
except Exception as e:
    print(f'direct eastmoney: {type(e).__name__}: {e}')

# Also try Tencent realtime
t0 = time.time()
url2 = f'https://qt.gtimg.cn/q=sh{symbol}'
try:
    resp = requests.get(url2, timeout=10)
    print(f'tencent qt: OK ({time.time()-t0:.1f}s) status={resp.status_code}')
    print(resp.text[:200])
except Exception as e:
    print(f'tencent qt: {type(e).__name__}: {e}')
