import requests
from datetime import datetime, timedelta, timezone

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

since_date = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime("%Y-%m-%d")
handles = ["jump_", "ambergroup_io", "FalconXGlobal"]

for h in handles:
    query = f"from:{h} since:{since_date}"
    resp = requests.get(
        "https://api.fxtwitter.com/2/search",
        params={"q": query}, timeout=10, headers=DEFAULT_HEADERS,
    )
    print("====", h, "query=", query, resp.status_code)
    data = resp.json()
    results = data.get("results", [])
    print("result count:", len(results))
    for r in results[:5]:
        print("  ", r.get("created_timestamp"), "|", (r.get("text") or "")[:60])
    print()
