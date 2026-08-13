#!/usr/bin/env python3
from __future__ import annotations
"""
fetch_news.py
-------------
Fetches crypto/forex/stock news from 35+ RSS feeds, deduplicates titles with
fuzzy matching, classifies sentiment via a tiered Groq / VADER / keyword-scorer
engine chain, and writes the result to news.json.
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
# Each feed carries:
#   category — CRYPTO | FOREX | STOCKS  (default article category before
#              per-article classification refines it further)
#   tier     — 1 (wire services / central banks / major financial media) ...
#              4 (blogs / aggregators). Drives sentiment-engine routing:
#              tier 1-2 -> Groq primary, tier 3-4 -> VADER primary.
RSS_FEEDS = [
    # ---- Crypto: tier 1 (majors / wire-service-grade) --------------------
    {"name": "CoinDesk",           "url": "https://www.coindesk.com/arc/outboundfeeds/rss/", "category": "CRYPTO", "tier": 1},
    {"name": "The Block",          "url": "https://www.theblock.co/rss.xml", "category": "CRYPTO", "tier": 1},
    {"name": "Blockworks",         "url": "https://blockworks.co/feed", "category": "CRYPTO", "tier": 1},

    # ---- Crypto: tier 2 (major financial/crypto media) --------------------
    {"name": "CoinTelegraph",      "url": "https://cointelegraph.com/rss", "category": "CRYPTO", "tier": 2},
    {"name": "Decrypt",            "url": "https://decrypt.co/feed", "category": "CRYPTO", "tier": 2},
    {"name": "CryptoSlate",        "url": "https://cryptoslate.com/feed/", "category": "CRYPTO", "tier": 2},
    {"name": "Bitcoin Magazine",   "url": "https://bitcoinmagazine.com/feed", "category": "CRYPTO", "tier": 2},
    {"name": "BeInCrypto",         "url": "https://beincrypto.com/feed/", "category": "CRYPTO", "tier": 2},
    {"name": "Investing.com Crypto","url": "https://www.investing.com/rss/news_301.rss", "category": "CRYPTO", "tier": 2},
    {"name": "FXStreet Crypto",    "url": "https://www.fxstreet.com/cryptocurrencies/news/rss", "category": "CRYPTO", "tier": 2},

    # ---- Crypto: tier 3-4 (blogs / aggregators) ----------------------------
    {"name": "CryptoPotato",       "url": "https://cryptopotato.com/feed/", "category": "CRYPTO", "tier": 3},
    {"name": "NewsBTC",            "url": "https://www.newsbtc.com/feed/", "category": "CRYPTO", "tier": 3},
    {"name": "Bitcoinist",         "url": "https://bitcoinist.com/feed/", "category": "CRYPTO", "tier": 3},
    {"name": "AMBCrypto",          "url": "https://ambcrypto.com/feed/", "category": "CRYPTO", "tier": 3},
    {"name": "Crypto Briefing",    "url": "https://cryptobriefing.com/feed/", "category": "CRYPTO", "tier": 3},
    {"name": "The Daily Hodl",     "url": "https://dailyhodl.com/feed/", "category": "CRYPTO", "tier": 3},
    {"name": "U.Today",            "url": "https://u.today/rss", "category": "CRYPTO", "tier": 3},
    {"name": "Crypto News",        "url": "https://cryptonews.com/news/feed/", "category": "CRYPTO", "tier": 3},
    {"name": "CoinJournal",        "url": "https://coinjournal.net/news/feed/", "category": "CRYPTO", "tier": 3},
    {"name": "Bitcoin.com News",   "url": "https://news.bitcoin.com/feed/", "category": "CRYPTO", "tier": 3},
    {"name": "Milk Road",          "url": "https://www.milkroad.com/feed", "category": "CRYPTO", "tier": 3},
    {"name": "Protos",             "url": "https://protos.com/feed/", "category": "CRYPTO", "tier": 3},
    {"name": "Unchained Crypto",   "url": "https://unchainedcrypto.com/feed/", "category": "CRYPTO", "tier": 3},
    {"name": "Bankless",           "url": "https://banklesshq.com/rss/", "category": "CRYPTO", "tier": 3},
    {"name": "The Defiant",        "url": "https://thedefiant.io/feed", "category": "CRYPTO", "tier": 3},
    {"name": "DL News",            "url": "https://www.dlnews.com/rss.xml", "category": "CRYPTO", "tier": 3},
    {"name": "Coingape",           "url": "https://coingape.com/feed/", "category": "CRYPTO", "tier": 4},
    {"name": "CoinQuora",          "url": "https://coinquora.com/feed/", "category": "CRYPTO", "tier": 4},
    {"name": "ZyCrypto",           "url": "https://zycrypto.com/feed/", "category": "CRYPTO", "tier": 4},
    {"name": "CryptoMode",         "url": "https://cryptomode.com/feed/", "category": "CRYPTO", "tier": 4},
    {"name": "CryptoGlobe",        "url": "https://www.cryptoglobe.com/latest/feed/", "category": "CRYPTO", "tier": 4},
    {"name": "Crypto Slate (PR)",  "url": "https://cryptoslate.com/press-releases/feed/", "category": "CRYPTO", "tier": 4},

    # ---- Forex / macro (tier 1: central banks, tier 2: FX media) ---------
    {"name": "Federal Reserve",    "url": "https://www.federalreserve.gov/feeds/press_all.xml", "category": "FOREX", "tier": 1},
    {"name": "ECB Press",          "url": "https://www.ecb.europa.eu/rss/press.html", "category": "FOREX", "tier": 1},
    {"name": "Bank of England",    "url": "https://www.bankofengland.co.uk/rss/news", "category": "FOREX", "tier": 1},
    {"name": "FXStreet",           "url": "https://www.fxstreet.com/rss/news", "category": "FOREX", "tier": 2},

    # ---- Stocks / regulatory (tier 1: SEC/wire, tier 2-3: media) ---------
    {"name": "SEC Press Releases", "url": "https://www.sec.gov/news/pressreleases.rss", "category": "STOCKS", "tier": 1},
    {"name": "MarketWatch",        "url": "https://feeds.content.dowjones.io/public/rss/mw_topstories", "category": "STOCKS", "tier": 2},
    {"name": "Seeking Alpha",      "url": "https://seekingalpha.com/market_currents.xml", "category": "STOCKS", "tier": 3},
]

# ---------------------------------------------------------------------------
# 2. DYNAMIC COIN REGISTRY & EXTRACTION
# ---------------------------------------------------------------------------
# Blacklist of common English noise words, modal verbs, or general abbreviations
# to ignore as tickers. Kept easy to extend — expect ongoing tuning as
# forex/stock tickers introduce more collisions with plain English words than
# crypto tickers did.
NOISE_WORDS = {
    "FOR", "AND", "ON", "OUT", "THE", "BUT", "ARE", "YOU", "ITS", "NOT", "HER", "HIS", "HIM",
    "WHO", "OUT", "GET", "PAY", "RUN", "KEY", "NEW", "BIG", "LOW", "TAX", "MAP", "NET", "WEB",
    "CAP", "DOT", "ETF", "SEC", "CEO", "USA", "FED", "LPs", "TVL", "APY", "APR", "ALL", "ANY",
    "ASK", "BAD", "BOY", "DAY", "DUE", "END", "FLY", "FUN", "GUY", "JOB", "LED", "LET", "LOT",
    "MAN", "MAY", "ONE", "OWN", "RED", "SAD", "SEE", "TRY", "TWO", "USE", "WAR", "WAY", "WIN",
    "YES", "YET", "AIR", "BOX", "CAR", "CAT", "DOG", "EAT", "EYE", "FIX", "HOT", "ICE", "MIX",
    "OFF", "OIL", "OLD", "RAW", "SEA", "SKY", "SON", "SUN", "TOY", "PRO", "WOULD", "COULD",
    "SHOULD", "WILL", "SHALL", "GAS", "HAS", "HAD", "HAVE", "ME", "GO", "BY", "IF", "OR", "TO",
    "AM", "AN", "AS", "BE", "MY", "NO", "SO", "OK", "NOW", "OUR", "WHY", "HOW", "FEW",
    # Added for forex/stocks/macro expansion — generic macro/news words observed
    # slipping through as false-positive tickers.
    "US", "DATA", "BILL", "CASH", "OPEN", "BEAT", "GDP", "IPO", "CPI", "PMI",
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

# Source credibility lookup — surfaced via `source_flag`, not filtered on.
# Consuming UI decides what to do with the flag. Keep easy to extend.
SOURCE_FLAGS: dict[str, str] = {
    "Xinhua": "state_media",
    "CGTN": "state_media",
    "Global Times": "state_media",
    "TASS": "state_media",
    "RT": "state_media",
    "Sputnik": "state_media",
    "Press TV": "state_media",
    "KCNA": "state_media",
}


DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def fetch_top_500_coingecko() -> dict[str, list[str]]:
    """
    Fetch the top 500 coins dynamically from CoinGecko markets API.
    Returns a dictionary mapping Symbol -> list of name variations (lowercased).
    """
    coins_map = {}
    fallback = {s: [kw.lower() for kw in kws] for s, kws in FALLBACK_COINS.items()}
    fetched_coins = []
    success = False

    try:
        # Fetch pages 1 and 2 (250 items per page = 500 total)
        for page in [1, 2]:
            url = f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=250&page={page}"
            resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=5)
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
    Format all coin/stock/forex tickers cleanly:
    1. Split any comma-joined entries (e.g. Groq sometimes returns "ADA,XRP"
       as a single array element instead of two).
    2. Strip leading '$' or '#' characters.
    3. Convert to uppercase.
    4. Remove any whitespace.
    5. Remove noise words.
    6. Return unique list (preserving order).
    """
    cleaned = []
    for t in tickers_list:
        if not t:
            continue
        for piece in str(t).split(","):
            t_str = piece.strip().upper().lstrip("$#").replace(" ", "")
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

# Region-inference keyword hints — simple heuristic used for articles that
# aren't classified by Groq (VADER/keyword-scored articles). Best-effort only.
REGION_KEYWORDS = {
    "US":    ["federal reserve", "fed ", "washington", "white house", "wall street", "sec ", "united states", " usd", "treasury"],
    "EU":    ["european central bank", "ecb", "eurozone", "brussels", "eur ", "european union"],
    "ASIA":  ["bank of japan", "boj", "china", "beijing", "tokyo", "yen", "yuan", "hong kong", "singapore"],
    "INDIA": ["rbi", "reserve bank of india", "sensex", "nifty", "rupee", "mumbai", "sebi"],
    "MENA":  ["saudi", "uae", "dubai", "qatar", "gulf", "opec", "middle east"],
}

# Category-inference keyword hints — same best-effort role as REGION_KEYWORDS.
CATEGORY_KEYWORDS = {
    "REGULATORY":  ["sec ", "lawsuit", "regulation", "regulator", "compliance", "settlement", "enforcement", "subpoena", "ban "],
    "ECONOMIC":    ["gdp", "inflation", "cpi", "pmi", "interest rate", "rate cut", "rate hike", "unemployment", "recession"],
    "GEOPOLITICS": ["war", "conflict", "sanctions", "geopolit", "invasion", "tariff"],
}


def matches_crypto_prefilter(title: str, summary: str) -> bool:
    combined = f"{title} {summary}".lower()
    return any(kw in combined for kw in CRYPTO_KEYWORDS)


def infer_region(text: str) -> str:
    text_lower = text.lower()
    for region, hints in REGION_KEYWORDS.items():
        if any(h in text_lower for h in hints):
            return region
    return "GLOBAL"


def infer_category(text: str, default: str) -> str:
    text_lower = text.lower()
    for category, hints in CATEGORY_KEYWORDS.items():
        if any(h in text_lower for h in hints):
            return category
    return default


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
            resp = requests.get(feed_meta["url"], timeout=3, headers=DEFAULT_HEADERS)
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
        except Exception as exc:
            print(f"[WARN] Failed to fetch {feed_meta['name']}: {exc}")
            continue

        feed_category = feed_meta.get("category", "CRYPTO")

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

            # Stage 1 Python Pre-Filter (Remove Non-Crypto Noise). Only applies
            # to CRYPTO-category feeds — forex/macro/stock news frequently has
            # no crypto-keyword overlap at all (e.g. "Fed holds rates steady")
            # and forex/stock feeds are already curated/on-topic by source.
            if feed_category == "CRYPTO" and not matches_crypto_prefilter(title, summary_clean):
                continue

            tickers = extract_coin_tags(f"{title} {summary_clean}", coin_keywords)

            articles.append({
                "title":     title,
                "url":       link,
                "source":    feed_meta["name"],
                "published": pub.isoformat() if pub else None,
                "tickers":   tickers,
                "summary":   summary_clean[:300].strip(),
                "_category": feed_category,
                "_tier":     feed_meta.get("tier", 3),
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
                "category":     article.get("_category", "CRYPTO"),
                "region":       "GLOBAL",
                "source_flag":  SOURCE_FLAGS.get(article["source"]),
                "sentiment_engine": None,
                "_tier":        article.get("_tier", 3),
            })

    return primary


# ---------------------------------------------------------------------------
# 5. TOKEN-BUDGET GUARD
# ---------------------------------------------------------------------------
# Verified Groq free-tier limits (llama-3.1-8b-instant), Aug 2026:
#   30 req/min, 14,400 req/day, 6,000 tokens/min, 500,000 tokens/day.
# Requests are not the constraint — tokens are. Stop routing to Groq once
# daily usage crosses ~75% of the TPD ceiling, and fall back to VADER, so a
# scrape run never dies mid-batch on a hard 429.
TOKEN_USAGE_FILE = os.path.join(os.path.dirname(__file__), "token_usage.json")
DAILY_TOKEN_LIMIT = 500_000
TOKEN_BUDGET_CUTOFF_RATIO = 0.75  # stop routing to Groq past this fraction of DAILY_TOKEN_LIMIT
CHARS_PER_TOKEN_ESTIMATE = 4  # rough estimate used before actual usage is known


def _load_token_usage() -> dict:
    today = datetime.now(timezone.utc).date().isoformat()
    if os.path.exists(TOKEN_USAGE_FILE):
        try:
            with open(TOKEN_USAGE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("date") == today:
                return data
        except Exception:
            pass
    return {"date": today, "tokens_used": 0}


def _save_token_usage(usage: dict) -> None:
    try:
        with open(TOKEN_USAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(usage, f)
    except Exception as exc:
        print(f"  [WARN] Failed to persist token usage counter: {exc}")


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN_ESTIMATE)


# ---------------------------------------------------------------------------
# 6. VADER (finance-tuned) + KEYWORD-SCORER FALLBACK ENGINES
# ---------------------------------------------------------------------------
try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    _VADER_AVAILABLE = True
except Exception:
    _VADER_AVAILABLE = False

# Finance-tuned lexicon overlay merged into VADER's analyzer before scoring.
# Weighted on VADER's -4..4 scale.
FINANCE_LEXICON_OVERLAY = {
    "surge": 3.2, "surges": 3.2, "surged": 3.2, "rally": 3.0, "rallies": 3.0,
    "soar": 3.3, "soars": 3.3, "soared": 3.3, "breakout": 2.5, "bullish": 3.0,
    "outperform": 2.2, "upgrade": 2.0, "upgraded": 2.0, "beat estimates": 2.5,
    "record high": 2.8, "all-time high": 2.8, "adoption": 1.8, "partnership": 1.5,
    "listing": 1.5, "burn": 1.8, "buyback": 1.8, "inflow": 1.6, "inflows": 1.6,
    "crash": -3.5, "crashes": -3.5, "crashed": -3.5, "plunge": -3.2, "plunges": -3.2,
    "plunged": -3.2, "slump": -2.8, "bearish": -3.0, "sell-off": -2.6, "selloff": -2.6,
    "downgrade": -2.0, "downgraded": -2.0, "hack": -3.3, "hacked": -3.3, "exploit": -3.0,
    "exploited": -3.0, "lawsuit": -2.2, "sued": -2.2, "delisting": -2.4, "delisted": -2.4,
    "bankruptcy": -3.4, "bankrupt": -3.4, "collapse": -3.2, "collapsed": -3.2,
    "outflow": -1.6, "outflows": -1.6, "dump": -2.0, "dumped": -2.0, "recession": -2.5,
    "default": -2.6, "shutdown": -2.0, "investigation": -1.8, "probe": -1.6,
}

_vader_analyzer = None
if _VADER_AVAILABLE:
    _vader_analyzer = SentimentIntensityAnalyzer()
    _vader_analyzer.lexicon.update(FINANCE_LEXICON_OVERLAY)


def classify_with_vader(text: str) -> tuple[str, float]:
    scores = _vader_analyzer.polarity_scores(text)
    compound = scores["compound"]
    if compound >= 0.2:
        return "Bullish", round(min(0.5 + abs(compound) / 2, 0.95), 4)
    if compound <= -0.2:
        return "Bearish", round(min(0.5 + abs(compound) / 2, 0.95), 4)
    return "Neutral", round(0.5 + abs(compound) / 4, 4)


# No-dependency keyword scorer — final fallback only if VADER itself is
# unavailable (e.g. package not installed in some environment).
KEYWORD_WEIGHTS = {
    "surge": 2, "rally": 2, "soar": 2, "bullish": 3, "record high": 2, "all-time high": 2,
    "adoption": 1, "partnership": 1, "upgrade": 1, "inflow": 1, "burn": 1, "buyback": 1,
    "crash": -2, "plunge": -2, "bearish": -3, "sell-off": -2, "selloff": -2, "downgrade": -1,
    "hack": -3, "exploit": -3, "lawsuit": -2, "delisting": -2, "bankruptcy": -3, "collapse": -3,
    "outflow": -1, "dump": -1, "recession": -2, "default": -2, "shutdown": -1, "investigation": -1,
}


def classify_with_keywords(text: str) -> tuple[str, float]:
    text_lower = text.lower()
    score = 0
    hits = 0
    for kw, weight in KEYWORD_WEIGHTS.items():
        if kw in text_lower:
            score += weight
            hits += 1
    if score > 0:
        return "Bullish", round(min(0.5 + min(score, 6) / 12, 0.9), 4)
    if score < 0:
        return "Bearish", round(min(0.5 + min(abs(score), 6) / 12, 0.9), 4)
    return "Neutral", 0.5


def classify_fallback(article: dict) -> None:
    """Route a single article through VADER, falling back to the keyword
    scorer if VADER isn't installed. Tags category/region via heuristics
    since neither engine returns them directly."""
    text = f"{article['title']}. {article.get('summary', '')}"
    if _VADER_AVAILABLE:
        sentiment, confidence = classify_with_vader(text)
        engine = "vader"
    else:
        sentiment, confidence = classify_with_keywords(text)
        engine = "keyword"

    article["sentiment"] = sentiment
    article["confidence"] = confidence
    article["is_crypto_relevant"] = True
    article["sentiment_engine"] = engine
    article["category"] = infer_category(text, article.get("category", "CRYPTO"))
    article["region"] = infer_region(text)


# ---------------------------------------------------------------------------
# 7. GROQ LLAMA 3 SENTIMENT ANALYSIS (tier 1/2 primary engine)
# ---------------------------------------------------------------------------
GROQ_SYSTEM_PROMPT = (
    "You are an expert Web3 quantitative sentiment analyst and elite tokenomics researcher, "
    "also fluent in forex and equity market analysis.\n"
    "Evaluate news items based on direct economic/market impact on the mentioned assets, NOT journalistic writing tone.\n\n"
    "BE OPINIONATED and analyze the actual fundamental impact. Do not default to 'Neutral' for news that has "
    "clear positive or negative fundamental implications. Classify as 'Bullish', 'Bearish', or 'Neutral' "
    "based on these guidelines:\n\n"
    "🟢 BULLISH catalysts:\n"
    "- Token burns, fee burn proposals, supply sinks, lock-up extensions, deflationary actions.\n"
    "- Mainstream corporate adoption (e.g. SpaceX, BlackRock, MicroStrategy entering or expanding).\n"
    "- Capital inflows, large venture funding rounds, investment stakes, rate cuts, dovish central bank tone.\n"
    "- Product upgrades, mainnet/testnet launches, earnings beats, major ecosystem partnerships.\n"
    "- Exchange listing announcements, ETF approvals, or regulatory wins against enforcement agencies.\n\n"
    "🔴 BEARISH risks:\n"
    "- Security incidents: hacks, exploits, smart contract vulnerabilities, funds stolen.\n"
    "- Tokenomics inflation: massive token unlocks, treasury liquidations, whale dumps.\n"
    "- Regulatory crackdowns: SEC lawsuits, delistings, bans, warning letters, rate hikes, hawkish central bank tone.\n"
    "- Protocol sunsetting, project shutdowns, network downtime, consensus failures, earnings misses.\n\n"
    "⚪ NEUTRAL indicators:\n"
    "- Routine node updates, scheduled maintenance, standard industry interviews, generic macro recaps, or articles with zero market directional bias.\n\n"
    "Few-Shot Examples:\n"
    "- \"NEAR Governance Votes to Scrap Developer Gas Rebate\" -> Sentiment: \"Bullish\", Reason: \"100% gas burn creates deflationary pressure.\"\n"
    "- \"SpaceX revenue nearly doubles... crypto markets paying attention\" -> Sentiment: \"Bullish\", Reason: \"Mainstream corporate growth driving crypto adoption.\"\n"
    "- \"DeFi Access Point SummerFi to Sunsets UI due to exploit\" -> Sentiment: \"Bearish\", Reason: \"Exploit and shutdown harms user trust and protocol activity.\"\n"
    "- \"Fed holds rates steady, signals no cuts before Q4\" -> Sentiment: \"Bearish\", Reason: \"Hawkish hold delays easing, pressures risk assets.\"\n\n"
    "For each item, also determine:\n"
    "- \"is_crypto_relevant\": true/false — whether the item is relevant to its asset class (crypto, forex, "
    "or stocks/macro) and worth surfacing to a trader in that space. Only set false for genuinely off-topic items.\n"
    "- \"category\": one of \"CRYPTO\", \"FOREX\", \"STOCKS\", \"MARKETS\", \"ECONOMIC\", \"REGULATORY\", \"GEOPOLITICS\".\n"
    "- \"region\": one of \"US\", \"EU\", \"ASIA\", \"INDIA\", \"MENA\", \"GLOBAL\".\n\n"
    "You MUST respond with a strict, valid JSON object containing a single key \"results\" mapping to an array of objects.\n"
    "Each object in the array must correspond to one of the input items and have these exact keys:\n"
    "- \"id\": integer (matching the input ID)\n"
    "- \"sentiment\": \"Bullish\" | \"Bearish\" | \"Neutral\"\n"
    "- \"confidence\": float\n"
    "- \"is_crypto_relevant\": boolean\n"
    "- \"tickers\": list of strings (capitalized tickers only)\n"
    "- \"category\": string (one of the categories above)\n"
    "- \"region\": string (one of the regions above)\n\n"
    "Example output:\n"
    "{\n"
    "  \"results\": [\n"
    "    {\"id\": 0, \"sentiment\": \"Bullish\", \"confidence\": 0.95, \"is_crypto_relevant\": true, \"tickers\": [\"NEAR\"], \"category\": \"CRYPTO\", \"region\": \"GLOBAL\"},\n"
    "    {\"id\": 1, \"sentiment\": \"Bearish\", \"confidence\": 0.90, \"is_crypto_relevant\": true, \"tickers\": [], \"category\": \"ECONOMIC\", \"region\": \"US\"}\n"
    "  ]\n"
    "}"
)

GROQ_BATCH_SIZE = 15
GROQ_MAX_RETRIES = 1  # one retry on 429, then fall to VADER for that batch


def _is_rate_limit_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "429" in msg or "rate limit" in msg or "rate_limit" in msg


def classify_batch_with_groq(client, batch: list[dict], usage: dict) -> bool:
    """
    Try to classify one batch via Groq. Returns True if the batch was
    successfully classified (and `usage` updated), False if it should fall
    back to VADER/keyword (budget exceeded, rate-limited after retry, or
    any other error).
    """
    items_prompt = [
        {"id": idx, "title": a["title"], "summary": a.get("summary", "")[:250]}
        for idx, a in enumerate(batch)
    ]
    user_prompt = f"Analyze these news items:\n{json.dumps(items_prompt, indent=2)}"

    # Token-budget guard: estimate this batch's cost and refuse if it would
    # push the day's usage past the cutoff ratio.
    estimated = _estimate_tokens(GROQ_SYSTEM_PROMPT) + _estimate_tokens(user_prompt) + 500
    if usage["tokens_used"] + estimated > DAILY_TOKEN_LIMIT * TOKEN_BUDGET_CUTOFF_RATIO:
        print(f"  [BUDGET] Projected usage would exceed {TOKEN_BUDGET_CUTOFF_RATIO:.0%} of daily token cap "
              f"({usage['tokens_used']}/{DAILY_TOKEN_LIMIT}) — routing batch to VADER instead.")
        return False

    attempts = 0
    while attempts <= GROQ_MAX_RETRIES:
        attempts += 1
        try:
            print(f"Sending batch of {len(batch)} headlines to Groq API (attempt {attempts})...")
            completion = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": GROQ_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                timeout=15,
            )

            response_text = completion.choices[0].message.content
            data = json.loads(response_text)
            results = data.get("results", [])

            results_map = {}
            for r in results:
                if isinstance(r, dict) and "id" in r:
                    results_map[r["id"]] = r

            for idx, a in enumerate(batch):
                r = results_map.get(idx)
                if r:
                    is_relevant = r.get("is_crypto_relevant", True)
                    if not is_relevant:
                        a["is_crypto_relevant"] = False
                        a["sentiment_engine"] = "groq"
                        continue

                    sentiment = str(r.get("sentiment", "Neutral")).strip().capitalize()
                    if sentiment not in ["Bullish", "Bearish", "Neutral"]:
                        sentiment = "Neutral"
                    a["sentiment"] = sentiment
                    a["confidence"] = round(float(r.get("confidence", 0.50)), 4)
                    a["is_crypto_relevant"] = True
                    a["sentiment_engine"] = "groq"

                    category = str(r.get("category", a.get("category", "CRYPTO"))).strip().upper()
                    if category:
                        a["category"] = category
                    region = str(r.get("region", "GLOBAL")).strip().upper()
                    if region:
                        a["region"] = region

                    if "tickers" in r and isinstance(r["tickers"], list):
                        a["tickers"] = clean_tickers(a.get("tickers", []) + r["tickers"])
                else:
                    # No result returned for this id — fall back for this article only.
                    classify_fallback(a)

            # Track actual token usage when the API reports it; otherwise estimate.
            actual_tokens = getattr(getattr(completion, "usage", None), "total_tokens", None)
            usage["tokens_used"] += actual_tokens if actual_tokens else estimated
            _save_token_usage(usage)
            return True

        except Exception as exc:
            if _is_rate_limit_error(exc) and attempts <= GROQ_MAX_RETRIES:
                print(f"  [WARN] Groq rate-limited (429). Retrying once after short backoff...")
                time.sleep(2.0)
                continue
            print(f"[WARN] Groq API call error on batch: {exc}. Falling back to VADER for this batch.")
            return False

    return False


def classify_sentiments(articles: list[dict]) -> list[dict]:
    """
    Tiered sentiment routing:
      - Tier 1/2 sources -> Groq primary, VADER fallback (rate limit/budget/error).
      - Tier 3/4 sources -> VADER primary by design (not just a fallback).
      - VADER unavailable -> keyword scorer as final fallback, any tier.
    Tags every article with which engine actually classified it via
    `sentiment_engine` ("groq" | "vader" | "keyword").
    """
    groq_key = os.environ.get("GROQ_API_KEY", "")
    client = None
    if groq_key:
        try:
            from groq import Groq
            client = Groq(api_key=groq_key)
        except Exception as exc:
            print(f"[WARN] Failed to initialize Groq client: {exc}. Tier 1/2 will fall back to VADER.")
            client = None
    else:
        print("[WARN] GROQ_API_KEY not set — all articles will route to VADER/keyword engines.")

    usage = _load_token_usage()
    print(f"  Token usage today: {usage['tokens_used']}/{DAILY_TOKEN_LIMIT} "
          f"({usage['tokens_used'] / DAILY_TOKEN_LIMIT:.1%})")

    tier12 = [a for a in articles if a.get("_tier", 3) <= 2]
    tier34 = [a for a in articles if a.get("_tier", 3) > 2]

    # Tier 1/2: Groq primary.
    if client and tier12:
        for idx_start in range(0, len(tier12), GROQ_BATCH_SIZE):
            batch = tier12[idx_start: idx_start + GROQ_BATCH_SIZE]
            ok = classify_batch_with_groq(client, batch, usage)
            if not ok:
                for a in batch:
                    if a.get("sentiment_engine") is None:
                        classify_fallback(a)
            time.sleep(0.5)
    else:
        for a in tier12:
            classify_fallback(a)

    # Tier 3/4: VADER primary by design — skip Groq entirely to conserve budget.
    for a in tier34:
        classify_fallback(a)

    print("✓ All sentiment classifications completed.")
    return articles


# ---------------------------------------------------------------------------
# 8. MAIN
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

    # 2. Merge incoming newly scraped articles by unique URL/title. Only
    # genuinely new stories get routed through sentiment classification —
    # already-scored republished/updated stories reuse their prior result.
    classified_stories = []
    to_classify = []

    for story in deduped:
        existing_story = existing_map.get(story["url"]) or existing_map.get(story["title"])
        if existing_story:
            # Reuse calculated fields
            story["sentiment"] = existing_story.get("sentiment", "Neutral")
            story["confidence"] = existing_story.get("confidence", 0.50)
            story["tickers"] = clean_tickers(list(set(story["tickers"] + existing_story.get("tickers", []))))
            story["category"] = existing_story.get("category", story.get("category", "CRYPTO"))
            story["region"] = existing_story.get("region", story.get("region", "GLOBAL"))
            story["sentiment_engine"] = existing_story.get("sentiment_engine")
            story["source_flag"] = existing_story.get("source_flag", story.get("source_flag"))
            # Merge alternate sources uniquely
            existing_alts = {alt["url"]: alt for alt in existing_story.get("other_sources", [])}
            for alt in story["other_sources"]:
                if alt["url"] not in existing_alts:
                    existing_story["other_sources"].append(alt)
            story["other_sources"] = existing_story["other_sources"]
            story["is_crypto_relevant"] = True  # Verified by virtue of existence
            story.pop("_tier", None)
            classified_stories.append(story)
        else:
            to_classify.append(story)

    print(f"  → {len(to_classify)} new stories need sentiment classification.")

    # 3. Classify brand new stories
    newly_classified = []
    if to_classify:
        classified_raw = classify_sentiments(to_classify)
        # Filter out any article where is_crypto_relevant is false
        newly_classified = [a for a in classified_raw if a.get("is_crypto_relevant", True)]
        for a in newly_classified:
            a.pop("_tier", None)

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

    usage = _load_token_usage()
    print(f"✓ Saved {len(final)} articles to {OUTPUT_FILE} and news.js")
    print(f"  Groq token usage today: {usage['tokens_used']}/{DAILY_TOKEN_LIMIT} "
          f"({usage['tokens_used'] / DAILY_TOKEN_LIMIT:.1%})")


if __name__ == "__main__":
    main()
