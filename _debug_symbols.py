import os, requests, json

key = os.environ["TWELVE_DATA_API_KEY"]
for q in ["dow jones", "nasdaq composite", "russell 2000", "vix", "s&p 500", "brent", "natural gas", "copper", "wti", "gold", "silver"]:
    r = requests.get("https://api.twelvedata.com/symbol_search", params={"symbol": q, "apikey": key}, timeout=10)
    data = r.json()
    print(f"=== {q} ===")
    for item in (data.get("data") or [])[:5]:
        print("  ", {k: item.get(k) for k in ("symbol", "instrument_name", "instrument_type", "exchange")})
    print()
