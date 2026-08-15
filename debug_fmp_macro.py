import os
import requests

api_key = os.environ.get("FMP_API_KEY", "")
base = "https://financialmodelingprep.com/stable"

resp = requests.get(f"{base}/market-risk-premium", params={"apikey": api_key}, timeout=10)
data = resp.json()
us = [d for d in data if "united states" in (d.get("country") or "").lower()]
print("US entries:", us)

resp2 = requests.get(f"{base}/economic-indicators", params={"name": "federalFunds", "apikey": api_key}, timeout=10)
print("federalFunds full:", resp2.json())
