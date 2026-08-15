import os
import requests

api_key = os.environ.get("FMP_API_KEY", "")
base = "https://financialmodelingprep.com/stable"

for name, url, params in [
    ("treasury-rates", f"{base}/treasury-rates", {"apikey": api_key}),
    ("economic-indicators(federalFunds)", f"{base}/economic-indicators", {"name": "federalFunds", "apikey": api_key}),
    ("market-risk-premium", f"{base}/market-risk-premium", {"apikey": api_key}),
]:
    resp = requests.get(url, params=params, timeout=10)
    data = resp.json()
    print("====", name, resp.status_code, "list_len:", len(data) if isinstance(data, list) else "n/a")
    print(str(data)[:600])
    print()
