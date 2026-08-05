#!/usr/bin/env python3
from __future__ import annotations
"""
fetch_news.py
-------------
Fetches crypto news from 30+ RSS feeds, deduplicates titles with fuzzy matching,
classifies sentiment via Groq Llama 3 API, and writes the result to news.json.
"""

import json
import os
import re
import time
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher

from typing import Optional
import feedparser
import requests

# ---------------------------------------------------------------------------
# 1. RSS FEED REGISTRY
# ---------------------------------------------------------------------------
RSS_FEEDS = [
    # Tier-1 majors
    {"name": "CoinTelegraph",      "url": "https://cointelegraph.com/rss"},
    {"name": "CoinDesk",           "url": "https://www.coindesk.com/arc/outboundfeeds/rss/"},
    {"name": "Decrypt",            "url": "https://decrypt.co/feed"},
    {"name": "CryptoSlate",        "url": "https://cryptoslate.com/feed/"},
    {"name": "The Block",          "url": "https://www.theblock.co/rss.xml"},
    {"name": "Blockworks",         "url": "https://blockworks.co/feed"},
    {"name": "Bitcoin Magazine",   "url": "https://bitcoinmagazine.com/feed"},
    {"name": "BeInCrypto",         "url": "https://beincrypto.com/feed/"},
    {"name": "CryptoPotato",       "url": "https://cryptopotato.com/feed/"},
    {"name": "NewsBTC",            "url": "https://www.newsbtc.com/feed/"},
    {"name": "Bitcoinist",         "url": "https://bitcoinist.com/feed/"},
    {"name": "AMBCrypto",          "url": "https://ambcrypto.com/feed/"},
    {"name": "Crypto Briefing",    "url": "https://cryptobriefing.com/feed/"},
    {"name": "The Daily Hodl",     "url": "https://dailyhodl.com/feed/"},
    {"name": "FXStreet Crypto",    "url": "https://www.fxstreet.com/cryptocurrencies/news/rss"},
    {"name": "U.Today",            "url": "https://u.today/rss"},
    {"name": "Crypto News",        "url": "https://cryptonews.com/news/feed/"},
    {"name": "CoinJournal",        "url": "https://coinjournal.net/news/feed/"},
    {"name": "Bitcoin.com News",   "url": "https://news.bitcoin.com/feed/"},
    {"name": "Coingape",           "url": "https://coingape.com/feed/"},
    {"name": "CoinQuora",          "url": "https://coinquora.com/feed/"},
    {"name": "ZyCrypto",           "url": "https://zycrypto.com/feed/"},
    {"name": "CryptoMode",         "url": "https://cryptomode.com/feed/"},
    {"name": "CryptoGlobe",        "url": "https://www.cryptoglobe.com/latest/feed/"},
    {"name": "Milk Road",          "url": "https://www.milkroad.com/feed"},
    {"name": "Protos",             "url": "https://protos.com/feed/"},
    {"name": "Unchained Crypto",   "url": "https://unchainedcrypto.com/feed/"},
    {"name": "Bankless",           "url": "https://banklesshq.com/rss/"},
    {"name": "The Defiant",        "url": "https://thedefiant.io/feed"},
    {"name": "DL News",            "url": "https://www.dlnews.com/rss.xml"},
    {"name": "Crypto Slate (PR)",  "url": "https://cryptoslate.com/press-releases/feed/"},
    {"name": "Investing.com Crypto","url": "https://www.investing.com/rss/news_301.rss"},
]

# ---------------------------------------------------------------------------
# 2. DYNAMIC COIN REGISTRY & EXTRACTION
# ---------------------------------------------------------------------------
# Blacklist of common English noise words, modal verbs, or general abbreviations to ignore as tickers
NOISE_WORDS = {
    "FOR", "AND", "ON", "OUT", "THE", "BUT", "ARE", "YOU", "ITS", "NOT", "HER", "HIS", "HIM",
    "WHO", "OUT", "GET", "PAY", "RUN", "KEY", "NEW", "BIG", "LOW", "TAX", "MAP", "NET", "WEB",
    "CAP", "DOT", "ETF", "SEC", "CEO", "USA", "FED", "LPs", "TVL", "APY", "APR", "ALL", "ANY",
    "ASK", "BAD", "BOY", "DAY", "DUE", "END", "FLY", "FUN", "GUY", "JOB", "LED", "LET", "LOT",
    "MAN", "MAY", "ONE", "OWN", "RED", "SAD", "SEE", "TRY", "TWO", "USE", "WAR", "WAY", "WIN",
    "YES", "YET", "AIR", "BOX", "CAR", "CAT", "DOG", "EAT", "EYE", "FIX", "HOT", "ICE", "MIX",
    "OFF", "OIL", "OLD", "RAW", "SEA", "SKY", "SON", "SUN", "TOY", "PRO", "WOULD", "COULD",
    "SHOULD", "WILL", "SHALL", "GAS", "HAS", "HAD", "HAVE", "ME", "GO", "BY", "IF", "OR", "TO",
    "AM", "AN", "AS", "BE", "MY", "NO", "SO", "OK", "NOW", "OUR", "WHY", "HOW", "FEW"
}

# Rich fallback dictionary in case of API rate limits
FALLBACK_COINS = {
    "BTC":    ["btc", "bitcoin"],
    "ETH":    ["eth", "ethereum", "ether"],
    "SOL":    ["sol", "solana"],
    "TIA":    ["tia", "celestia"],
    "KAS":    ["kas", "kaspa"],
    "TAO":    ["tao", "bittensor"],
    "RENDER": ["render"],
    "FET":    ["fet", "artificial superintelligence", "fetch.ai"],
    "SUI":    ["sui"],
    "PEPE":   ["pepe"],
    "XRP":    ["xrp", "ripple"],
    "ADA":    ["ada", "cardano"],
    "DOGE":   ["doge", "dogecoin"],
    "AVAX":   ["avax", "avalanche"],
    "LINK":   ["link", "chainlink"],
    "DOT":    ["dot", "polkadot"],
    "NEAR":   ["near", "near protocol"],
    "BNB":    ["bnb", "binance coin", "binance"],
    "SHIB":   ["shib", "shiba inu", "shiba"],
    "LTC":    ["ltc", "litecoin"],
    "TRX":    ["trx", "tron"],
    "TON":    ["ton", "toncoin"],
    "ATOM":   ["atom", "cosmos"],
    "MATIC":  ["matic", "polygon"],
    "ARB":    ["arb", "arbitrum"],
    "OP":     ["op", "optimism"],
    "UNI":    ["uni", "uniswap"],
    "AAVE":   ["aave"],
    "MKR":    ["mkr", "maker"],
    "CRV":    ["crv", "curve"],
    "LDO":    ["ldo", "lido"],
    "WIF":    ["wif", "dogwifhat"],
    "BONK":   ["bonk"],
    "INJ":    ["inj", "injective"],
    "SEI":    ["sei"],
    "APT":    ["apt", "aptos"],
    "FTM":    ["ftm", "fantom"],
    "ALGO":   ["algo", "algorand"],
    "HBAR":   ["hbar", "hedera"],
    "VET":    ["vet", "vechain"],
    "FIL":    ["fil", "filecoin"],
    "ICP":    ["icp", "internet computer"],
    "GRT":    ["grt", "the graph"],
    "SAND":   ["sand", "sandbox"],
    "MANA":   ["mana", "decentraland"],
    "AXS":    ["axs", "axie infinity"],
    "XLM":    ["xlm", "stellar"],
    "XMR":    ["xmr", "monero"],
    "BCH":    ["bch", "bitcoin cash"],
    "ETC":    ["etc", "ethereum classic"],
    "FLOKI":  ["floki"],
    "WLD":    ["wld", "worldcoin"],
    "STX":    ["stx", "stacks"],
    "RUNE":   ["rune", "thorchain"],
}


def fetch_top_500_coingecko() -> dict[str, list[str]]:
    """
    Fetch the top 500 coins dynamically from CoinGecko markets API.
    Returns a dictionary mapping Symbol -> list of name variations (lowercased).
    """
    coins_map = {}
    fallback = {s: [kw.lower() for kw in kws] for s, kws in FALLBACK_COINS.items()}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    fetched_coins = []
    success = False

    try:
        # Fetch pages 1 and 2 (250 items per page = 500 total)
        for page in [1, 2]:
            url = f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=250&page={page}"
            resp = requests.get(url, headers=headers, timeout=5)
            resp.raise_for_status()
            fetched_coins.extend(resp.json())
        success = True
    except Exception as exc:
        print(f"  [WARN] CoinGecko API request failed: {exc}. Using fallback list.")

    if not success or not fetched_coins:
        return fallback

    # Process dynamic list
    for coin in fetched_coins:
        symbol = coin.get("symbol", "").upper()
        name = coin.get("name", "")
        if not symbol or not name:
            continue

        if len(symbol) < 2:
            continue

        if symbol not in coins_map:
            coins_map[symbol] = []

        name_lower = name.lower()
        symbol_lower = symbol.lower()
        variations = {name_lower, symbol_lower}

        # Strip common decorations like " (old)" or " Token"
        cleaned = re.sub(r"\s*\(.*?\)\s*", "", name_lower)
        cleaned = re.sub(r"\b(token|coin|protocol)\b", "", cleaned).strip()
        if len(cleaned) >= 3:
            variations.add(cleaned)

        for var in variations:
            if var not in coins_map[symbol]:
                coins_map[symbol].append(var)

    # Ensure fallback coins are fully merged
    for symbol, keywords in fallback.items():
        if symbol not in coins_map:
            coins_map[symbol] = keywords
        else:
            for kw in keywords:
                if kw not in coins_map[symbol]:
                    coins_map[symbol].append(kw)

    print(f"  ✓ Dynamic coin registry initialized with {len(coins_map)} tickers.")
    return coins_map


def clean_tickers(tickers_list: list[str]) -> list[str]:
    """
    Format all coin tickers cleanly:
    1. Strip leading '$' or '#' characters.
    2. Convert to uppercase.
    3. Remove any whitespace.
    4. Remove noise words.
    5. Return unique list (preserving order).
    """
    cleaned = []
    for t in tickers_list:
        if not t:
            continue
        # Convert to string, strip whitespace, uppercase
        t_str = str(t).strip().upper()
        # Strip leading '$' or '#'
        t_str = t_str.lstrip("$#")
        # Remove any inner whitespace
        t_str = t_str.replace(" ", "")
        
        if t_str and t_str not in NOISE_WORDS:
            cleaned.append(t_str)
            
    return list(dict.fromkeys(cleaned))


def extract_coin_tags(text: str, coin_keywords: dict[str, list[str]]) -> list[str]:
    """Return a deduplicated list of coin tickers found in *text*."""
    text_lower = text.lower()
    found = []

    for symbol, keywords in coin_keywords.items():
        # 1. Case-sensitive ticker search to avoid noise/lowercase clashes (e.g. SUI vs sui)
        if symbol not in NOISE_WORDS:
            pattern = r"\b" + re.escape(symbol) + r"\b"
            if re.search(pattern, text):
                found.append(symbol)
                continue

        # 2. Case-insensitive search on name variations/keywords
        for kw in keywords:
            if kw.upper() in NOISE_WORDS or len(kw) < 3:
                continue
            pattern = r"\b" + re.escape(kw) + r"\b"
            if re.search(pattern, text_lower):
                found.append(symbol)
                break

    return clean_tickers(found)


# ---------------------------------------------------------------------------
# 3. RSS FETCHING
# ---------------------------------------------------------------------------
CUTOFF_HOURS = 48  # only keep articles published within this window

CRYPTO_KEYWORDS = [
    'btc', 'bitcoin', 'eth', 'ethereum', 'crypto', 'web3', 'defi', 'nft', 'token', 'blockchain',
    'sec', 'fed', 'binance', 'coinbase', 'solana', 'altcoin', 'etf', 'prediction market',
    'stablecoin', 'yield', 'staking', 'dao', 'governance', 'hack', 'exploit', 'airdrop'
]


def matches_crypto_prefilter(title: str, summary: str) -> bool:
    combined = f"{title} {summary}".lower()
    return any(kw in combined for kw in CRYPTO_KEYWORDS)


def parse_published(entry) -> Optional[datetime]:
    """Parse the published date from a feed entry, return UTC datetime or None."""
    ts = entry.get("published_parsed") or entry.get("updated_parsed")
    if ts:
        try:
            return datetime(*ts[:6], tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def fetch_all_feeds(coin_keywords: dict[str, list[str]]) -> list[dict]:
    """Fetch articles from all RSS_FEEDS within the past CUTOFF_HOURS."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=CUTOFF_HOURS)
    articles: list[dict] = []

    for feed_meta in RSS_FEEDS:
        try:
            # Fetch feed with a strict 3-second network timeout
            resp = requests.get(feed_meta["url"], timeout=3, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
        except Exception as exc:
            print(f"[WARN] Failed to fetch {feed_meta['name']}: {exc}")
            continue

        for entry in feed.entries:
            pub = parse_published(entry)
            if pub and pub < cutoff:
                continue  # too old

            title = (entry.get("title") or "").strip()
            if not title:
                continue

            link = entry.get("link") or entry.get("id") or ""
            summary = entry.get("summary") or entry.get("description") or ""
            # Strip HTML tags from summary for coin-tag extraction
            summary_clean = re.sub(r"<[^>]+>", " ", summary).strip()

            # Stage 1 Python Pre-Filter (Remove Non-Crypto Noise)
            if not matches_crypto_prefilter(title, summary_clean):
                continue

            tickers = extract_coin_tags(f"{title} {summary_clean}", coin_keywords)

            articles.append({
                "title":     title,
                "url":       link,
                "source":    feed_meta["name"],
                "published": pub.isoformat() if pub else None,
                "tickers":   tickers,
                "summary":   summary_clean[:300].strip(),
            })

    return articles


# ---------------------------------------------------------------------------
# 4. FUZZY DEDUPLICATION
# ---------------------------------------------------------------------------
SIMILARITY_THRESHOLD = 0.70  # titles >= 70% similar → group as duplicate


def titles_are_similar(a: str, b: str) -> bool:
    ratio = SequenceMatcher(None, a.lower(), b.lower()).ratio()
    return ratio >= SIMILARITY_THRESHOLD


def deduplicate(articles: list[dict]) -> list[dict]:
    """
    Group articles with similar titles (>= 70%) into a single card.
    The first-seen article becomes the primary; subsequent duplicates are
    appended to its `other_sources` list.
    """
    primary: list[dict] = []  # list of deduplicated story records

    for article in articles:
        title = article["title"]
        tickers = set(article["tickers"])
        matched = False

        for existing in primary:
            # Only fuzz-match within shared coin context (or both global)
            existing_tickers = set(existing["tickers"])
            shares_ticker = bool(tickers & existing_tickers) or (not tickers and not existing_tickers)

            if shares_ticker and titles_are_similar(title, existing["title"]):
                # Duplicate – add as an alternate source
                existing["other_sources"].append({
                    "source":    article["source"],
                    "url":       article["url"],
                    "published": article["published"],
                })
                matched = True
                break

        if not matched:
            primary.append({
                "title":        article["title"],
                "url":          article["url"],
                "source":       article["source"],
                "published":    article["published"],
                "tickers":      article["tickers"],
                "summary":      article.get("summary", ""),
                "sentiment":    None,
                "confidence":   None,
                "other_sources": [],
            })

    return primary


# ---------------------------------------------------------------------------
# 5. GROQ LLAMA 3 SENTIMENT ANALYSIS
# ---------------------------------------------------------------------------
def classify_sentiments(articles: list[dict]) -> list[dict]:
    """
    POST article titles to Groq API (llama-3.1-8b-instant) in batches of 15.
    Falls back to Neutral=0.50 on any error, timeout, or missing key.
    """
    groq_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_key:
        print("[WARN] GROQ_API_KEY not set — skipping sentiment, defaulting to Neutral (0.50).")
        for a in articles:
            a["sentiment"]  = "Neutral"
            a["confidence"] = 0.50
            a["is_crypto_relevant"] = True
        return articles

    try:
        from groq import Groq
        client = Groq(api_key=groq_key)
    except Exception as exc:
        print(f"[WARN] Failed to initialize Groq client: {exc}. Defaulting to Neutral (0.50).")
        for a in articles:
            a["sentiment"]  = "Neutral"
            a["confidence"] = 0.50
            a["is_crypto_relevant"] = True
        return articles

    BATCH_SIZE = 15
    for idx_start in range(0, len(articles), BATCH_SIZE):
        batch = articles[idx_start : idx_start + BATCH_SIZE]
        
        # Format batch content for prompt
        items_prompt = []
        for idx, a in enumerate(batch):
            items_prompt.append({
                "id": idx,
                "title": a["title"],
                "summary": a.get("summary", "")[:250]
            })

        system_prompt = (
            "You are an expert Web3 quantitative sentiment analyst and elite tokenomics researcher.\n"
            "Evaluate news items based on direct economic and tokenomics impact on the mentioned coins, NOT journalistic writing tone.\n\n"
            "BE OPINIONATED and analyze the actual fundamental impact. Do not default to 'Neutral' for news that has "
            "clear positive or negative fundamental implications. Classify as 'Bullish', 'Bearish', or 'Neutral' "
            "based on these guidelines:\n\n"
            "🟢 BULLISH catalysts:\n"
            "- Token burns, fee burn proposals, supply sinks, lock-up extensions, deflationary actions.\n"
            "- Mainstream corporate adoption (e.g. SpaceX, BlackRock, MicroStrategy entering or expanding).\n"
            "- Capital inflows, large venture funding rounds, investment stakes.\n"
            "- Product upgrades, mainnet/testnet launches, prediction market volume surges, major ecosystem partnerships.\n"
            "- Exchange listing announcements, ETF approvals, or regulatory wins against enforcement agencies.\n\n"
            "🔴 BEARISH risks:\n"
            "- Security incidents: hacks, exploits, smart contract vulnerabilities, funds stolen.\n"
            "- Tokenomics inflation: massive token unlocks, supply diluting unlocks, treasury liquidations, whale dumps.\n"
            "- Regulatory crackdowns: SEC lawsuits, delistings, bans, warning letters.\n"
            "- Protocol sunsetting, project shutdowns, network downtime, consensus failures.\n\n"
            "⚪ NEUTRAL indicators:\n"
            "- Routine node updates, scheduled maintenance, standard industry interviews, generic macro recaps, or articles with zero market directional bias.\n\n"
            "Few-Shot Examples:\n"
            "- \"NEAR Governance Votes to Scrap Developer Gas Rebate\" -> Sentiment: \"Bullish\", Reason: \"100% gas burn creates deflationary pressure.\"\n"
            "- \"SpaceX revenue nearly doubles... crypto markets paying attention\" -> Sentiment: \"Bullish\", Reason: \"Mainstream corporate growth driving crypto adoption.\"\n"
            "- \"DeFi Access Point SummerFi to Sunsets UI due to exploit\" -> Sentiment: \"Bearish\", Reason: \"Exploit and shutdown harms user trust and protocol activity.\"\n\n"
            "For each item, determine if it is relevant to cryptocurrencies (set is_crypto_relevant to true/false).\n\n"
            "You MUST respond with a strict, valid JSON object containing a single key \"results\" mapping to an array of objects.\n"
            "Each object in the array must correspond to one of the input items and have these exact keys:\n"
            "- \"id\": integer (matching the input ID)\n"
            "- \"sentiment\": \"Bullish\" | \"Bearish\" | \"Neutral\"\n"
            "- \"confidence\": float\n"
            "- \"is_crypto_relevant\": boolean\n"
            "- \"tickers\": list of strings (capitalized tickers only)\n\n"
            "Example output:\n"
            "{\n"
            "  \"results\": [\n"
            "    {\"id\": 0, \"sentiment\": \"Bullish\", \"confidence\": 0.95, \"is_crypto_relevant\": true, \"tickers\": [\"NEAR\"]},\n"
            "    {\"id\": 1, \"sentiment\": \"Bearish\", \"confidence\": 0.90, \"is_crypto_relevant\": true, \"tickers\": [\"AAVE\"]}\n"
            "  ]\n"
            "}"
        )

        user_prompt = f"Analyze these news items:\n{json.dumps(items_prompt, indent=2)}"

        # Default values for batch in case of error
        for a in batch:
            if a.get("sentiment") is None:
                a["sentiment"]  = "Neutral"
                a["confidence"] = 0.50
                a["is_crypto_relevant"] = True

        try:
            print(f"Sending batch of {len(batch)} headlines to Groq API...")
            completion = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                timeout=15,
            )
            
            response_text = completion.choices[0].message.content
            data = json.loads(response_text)
            results = data.get("results", [])
            
            # Map results back to the batch articles using the 'id'
            results_map = {}
            for r in results:
                if isinstance(r, dict) and "id" in r:
                    results_map[r["id"]] = r
                    
            for idx, a in enumerate(batch):
                r = results_map.get(idx)
                if r:
                    # Filter out any article where is_crypto_relevant is false
                    is_relevant = r.get("is_crypto_relevant", True)
                    if not is_relevant:
                        a["is_crypto_relevant"] = False
                        continue
                    
                    sentiment = str(r.get("sentiment", "Neutral")).strip().capitalize()
                    if sentiment not in ["Bullish", "Bearish", "Neutral"]:
                        sentiment = "Neutral"
                    a["sentiment"] = sentiment
                    a["confidence"] = round(float(r.get("confidence", 0.50)), 4)
                    a["is_crypto_relevant"] = True
                    
                    # Merge Groq-detected tickers with our regex-detected tickers for maximum coverage
                    if "tickers" in r and isinstance(r["tickers"], list):
                        a["tickers"] = clean_tickers(a.get("tickers", []) + r["tickers"])
        except Exception as exc:
            print(f"[WARN] Groq API call error or rate limit hit on batch: {exc}. Defaulting batch to Neutral (0.50).")
            
        time.sleep(0.5)

    print("✓ All sentiment classifications completed.")
    return articles


# ---------------------------------------------------------------------------
# 6. MAIN
# ---------------------------------------------------------------------------
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "news.json")


def main():
    print(f"[{datetime.now().isoformat()}] Fetching CoinGecko coin registry…")
    coin_keywords = fetch_top_500_coingecko()

    # 1. Read existing articles from news.json (if present)
    existing_articles = []
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                old_data = json.load(f)
                existing_articles = old_data.get("articles", [])
                print(f"  ✓ Loaded {len(existing_articles)} existing articles from news.json.")
        except Exception as exc:
            print(f"  [WARN] Failed to load existing news.json: {exc}")

    # Build lookup table by URL and Title
    existing_map = {}
    for a in existing_articles:
        if a.get("url"):
            existing_map[a["url"]] = a
        if a.get("title"):
            existing_map[a["title"]] = a

    print(f"[{datetime.now().isoformat()}] Fetching RSS feeds…")
    raw = fetch_all_feeds(coin_keywords)
    print(f"  → {len(raw)} raw articles fetched.")

    print("Deduplicating…")
    deduped = deduplicate(raw)
    print(f"  → {len(deduped)} unique stories after deduplication.")

    # Sort deduplicated stories newest first
    deduped.sort(key=lambda x: x["published"] or "", reverse=True)

    # 2. Merge incoming newly scraped articles by unique URL/title
    classified_stories = []
    to_classify = []

    for story in deduped:
        existing_story = existing_map.get(story["url"]) or existing_map.get(story["title"])
        if existing_story:
            # Reuse calculated fields
            story["sentiment"] = existing_story.get("sentiment", "Neutral")
            story["confidence"] = existing_story.get("confidence", 0.50)
            story["tickers"] = clean_tickers(list(set(story["tickers"] + existing_story.get("tickers", []))))
            # Merge alternate sources uniquely
            existing_alts = {alt["url"]: alt for alt in existing_story.get("other_sources", [])}
            for alt in story["other_sources"]:
                if alt["url"] not in existing_alts:
                    existing_story["other_sources"].append(alt)
            story["other_sources"] = existing_story["other_sources"]
            story["is_crypto_relevant"] = True  # Verified by virtue of existence
            classified_stories.append(story)
        else:
            to_classify.append(story)

    print(f"  → {len(to_classify)} new stories need Groq sentiment classification.")
    
    # 3. Classify brand new stories
    newly_classified = []
    if to_classify:
        classified_raw = classify_sentiments(to_classify)
        # Filter out any article where is_crypto_relevant is false
        newly_classified = [a for a in classified_raw if a.get("is_crypto_relevant", True)]

    # Combine old-reused and new-classified stories
    combined = classified_stories + newly_classified

    # 4. Discard articles with timestamps older than 48 hours
    cutoff = datetime.now(timezone.utc) - timedelta(hours=CUTOFF_HOURS)
    final = []
    for a in combined:
        if a.get("published"):
            try:
                pub_dt = datetime.fromisoformat(a["published"])
                if pub_dt >= cutoff:
                    final.append(a)
            except Exception:
                final.append(a)  # Keep if parsing fails
        else:
            final.append(a)

    # Sort newest first
    final.sort(key=lambda x: x["published"] or "", reverse=True)

    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total":      len(final),
        "articles":   final,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    JS_FILE = os.path.join(os.path.dirname(__file__), "news.js")
    with open(JS_FILE, "w", encoding="utf-8") as f:
        f.write(f"window.newsData = {json.dumps(output, ensure_ascii=False, indent=2)};")

    print(f"✓ Saved {len(final)} articles to {OUTPUT_FILE} and news.js")


if __name__ == "__main__":
    main()
