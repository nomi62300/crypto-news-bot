import os
import requests

api_key = os.environ.get("TWELVE_DATA_API_KEY", "")
print("key present:", bool(api_key), "len:", len(api_key))

for symbol in ["SPY", "USO", "GLD"]:
    resp = requests.get(
        "https://api.twelvedata.com/time_series",
        params={"symbol": symbol, "interval": "1day", "outputsize": 7, "apikey": api_key},
        timeout=10,
    )
    print("====", symbol, resp.status_code)
    print(resp.text[:1000])
