import time
import requests

url = "https://vfat.lptracker.info/api/positions"
print(f"Hitting {url} ...")
start = time.time()
try:
    resp = requests.get(url, timeout=60)
    elapsed = time.time() - start
    print(f"Status: {resp.status_code}, elapsed: {elapsed:.2f}s")
    print(f"Body (first 2000 chars): {resp.text[:2000]}")
except Exception as e:
    elapsed = time.time() - start
    print(f"FAILED after {elapsed:.2f}s: {type(e).__name__}: {e}")
