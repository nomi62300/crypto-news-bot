import requests

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

handles = ["wintermute_t", "ambergroup_io", "justinsuntron", "jump_", "FalconXGlobal"]

for h in handles:
    query = f"from:{h}"
    resp = requests.get(
        "https://api.fxtwitter.com/2/search",
        params={"q": query}, timeout=10, headers=DEFAULT_HEADERS,
    )
    print("====", h, resp.status_code)
    try:
        data = resp.json()
        results = data.get("results", [])
        print("result count:", len(results))
        for r in results[:2]:
            author = r.get("author", {})
            print("  author.screen_name:", author.get("screen_name"), "| text:", (r.get("text") or "")[:80])
    except Exception as e:
        print("parse error:", e, resp.text[:300])
    print()
