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
from urllib.parse import urljoin

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

# Maps a feed's coarse category to the asset_class output field (lowercase,
# distinct from the more granular `category` field which can be
# ECONOMIC/REGULATORY/etc.). "geopolitics" is a 4th value used only by
# structured-event sources (GDELT/USGS) — those don't go through Groq/FinBERT
# text-sentiment classification at all (see classify_geo_events()), so this
# is kept separate from the crypto/forex/stocks routing rather than folded
# into one of them.
ASSET_CLASS_BY_CATEGORY = {"CRYPTO": "crypto", "FOREX": "forex", "STOCKS": "stocks", "GEOPOLITICS": "geopolitics"}

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

# Major currencies for forex article tagging. Static/small by design (unlike
# the dynamic CoinGecko-backed crypto registry) — populates `currency_pairs`
# with constituent currency codes found in the text, not full pairs.
FOREX_CURRENCIES: dict[str, list[str]] = {
    "USD": ["dollar", "us dollar", "greenback"],
    "EUR": ["euro"],
    "GBP": ["pound", "sterling", "british pound"],
    "JPY": ["yen", "japanese yen"],
    "AUD": ["aussie", "australian dollar"],
    "CAD": ["loonie", "canadian dollar"],
    "CHF": ["swiss franc", "franc"],
    "NZD": ["kiwi", "new zealand dollar"],
    "CNY": ["yuan", "renminbi"],
}

# Stock tickers for STOCKS-category article tagging. Seeded with the live
# Bybit "xStocks" tokenized-stock universe (confirmed via Bybit's
# instruments-info API, symbolType == "xstocks", Aug 2026) so tag coverage
# matches what Wicktor's frontend can actually display. Keep easy to extend
# as that universe grows — same pattern as FALLBACK_COINS/NOISE_WORDS.
STOCK_TICKERS: dict[str, list[str]] = {
    "AAPL": ["aapl", "apple"],
    "AMZN": ["amzn", "amazon"],
    "COIN":  ["coin", "coinbase"],
    "CRCL": ["crcl", "circle"],
    "GOOGL": ["googl", "google", "alphabet"],
    "HOOD": ["hood", "robinhood"],
    "MCD":  ["mcd", "mcdonald's", "mcdonalds"],
    "META": ["meta", "facebook"],
    "NVDA": ["nvda", "nvidia"],
    "SPCX": ["spcx"],
    "TSLA": ["tsla", "tesla"],
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


def extract_currency_codes(text: str) -> list[str]:
    """Return deduplicated forex currency codes found in *text* (constituent
    currencies, not full pairs — e.g. "EUR/USD" -> ["EUR", "USD"])."""
    return extract_coin_tags(text, FOREX_CURRENCIES)


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

            combined_text = f"{title} {summary_clean}"
            # Ticker extraction routes by the feed's own asset class rather
            # than always searching the crypto registry — STOCKS feeds search
            # STOCK_TICKERS (previously always searched crypto and so never
            # matched anything), FOREX feeds populate currency_pairs instead
            # of tickers (a currency isn't a ticker).
            currency_pairs: list[str] = []
            if feed_category == "STOCKS":
                tickers = extract_coin_tags(combined_text, STOCK_TICKERS)
            elif feed_category == "FOREX":
                tickers = []
                currency_pairs = extract_currency_codes(combined_text)
            else:
                tickers = extract_coin_tags(combined_text, coin_keywords)

            articles.append({
                "title":     title,
                "url":       link,
                "source":    feed_meta["name"],
                "published": pub.isoformat() if pub else None,
                "tickers":   tickers,
                "currency_pairs": currency_pairs,
                "summary":   summary_clean[:300].strip(),
                "_category": feed_category,
                "_tier":     feed_meta.get("tier", 3),
                "_asset_class": ASSET_CLASS_BY_CATEGORY.get(feed_category, "crypto"),
            })

    return articles


# ---------------------------------------------------------------------------
# 3b. SCRAPLING SOURCES (non-RSS sites, adaptive HTML parsing)
# ---------------------------------------------------------------------------
# Optional dependency, same graceful-degradation pattern as VADER/FinBERT —
# base package only (NOT scrapling[fetchers], which pulls a full browser and
# is unnecessary here since these targets are server-rendered HTML fetched
# via plain requests).
try:
    from scrapling.parser import Adaptor as _ScraplingAdaptor
    _SCRAPLING_AVAILABLE = True
except Exception as exc:
    print(f"  [WARN] Scrapling unavailable ({exc}). Non-RSS sources will be skipped.")
    _ScraplingAdaptor = None
    _SCRAPLING_AVAILABLE = False

# Each entry's selectors were hand-verified against a live fetch of the site
# (not guessed) — title/link selectors use attribute-*contains* matching
# (`[class*="..."]`) rather than exact hashed class names where the site uses
# a CSS-modules/webpack build, since those hashes change on every redeploy;
# the stable substring is kept, the build-specific prefix is not matched.
SCRAPLING_SOURCES = [
    {
        "name": "InvestingLive", "url": "https://investinglive.com/",
        "category": "FOREX", "tier": 2,
        "title_selector": 'h3[class*="articleSlotHeader__title"]::text',
        "link_selector":  'a[class*="articleSlotHeader"]::attr(href)',
    },
    {
        "name": "Watcher.Guru", "url": "https://watcher.guru/news/",
        "category": "CRYPTO", "tier": 3,
        "title_selector": '.cs-entry__title a::text',
        "link_selector":  '.cs-entry__title a::attr(href)',
    },
]


def fetch_scrapling_sources(coin_keywords: dict[str, list[str]]) -> list[dict]:
    """Fetch article listings from non-RSS sites via Scrapling's adaptive
    CSS-selector parsing. Emits the exact same article dict shape as
    fetch_all_feeds() so deduplicate()/classify_sentiments()/main()'s
    dedup-reuse logic all handle these identically to an RSS article — only
    the fetch mechanism differs."""
    if not _SCRAPLING_AVAILABLE:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=CUTOFF_HOURS)
    articles: list[dict] = []

    def _as_text(value) -> str:
        # Scrapling's .css() with a `::text`/`::attr()` pseudo-selector can
        # return plain strings, or Selector/TextHandler-like wrapper objects
        # depending on version/match shape — normalize defensively via
        # .get() (Scrapy/parsel-style) before falling back to str().
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        getter = getattr(value, "get", None)
        if callable(getter):
            try:
                got = getter()
                return got if isinstance(got, str) else str(got or "")
            except Exception:
                pass
        return str(value)

    for source_meta in SCRAPLING_SOURCES:
        try:
            resp = requests.get(source_meta["url"], timeout=5, headers=DEFAULT_HEADERS)
            resp.raise_for_status()
            page = _ScraplingAdaptor(resp.text, url=source_meta["url"])
            titles = page.css(source_meta["title_selector"])
            links = page.css(source_meta["link_selector"])
        except Exception as exc:
            print(f"[WARN] Failed to fetch {source_meta['name']}: {exc}")
            continue

        source_category = source_meta.get("category", "CRYPTO")
        seen_urls_this_source = set()  # listing pages often repeat a "featured" item

        try:
            for title, link in zip(titles, links):
                title = _as_text(title).strip()
                link = _as_text(link).strip()
                if not title or not link:
                    continue
                url = urljoin(source_meta["url"], link)
                if url in seen_urls_this_source:
                    continue
                seen_urls_this_source.add(url)

                if source_category == "CRYPTO" and not matches_crypto_prefilter(title, ""):
                    continue

                currency_pairs: list[str] = []
                if source_category == "STOCKS":
                    tickers = extract_coin_tags(title, STOCK_TICKERS)
                elif source_category == "FOREX":
                    tickers = []
                    currency_pairs = extract_currency_codes(title)
                else:
                    tickers = extract_coin_tags(title, coin_keywords)

                # Listing pages don't reliably expose per-article timestamps in a
                # consistent, parseable format across sites — omit `published`
                # (None) rather than guess; downstream sorting/cutoff logic
                # already tolerates a missing published date (see main()).
                articles.append({
                    "title":     title,
                    "url":       url,
                    "source":    source_meta["name"],
                    "published": None,
                    "tickers":   tickers,
                    "currency_pairs": currency_pairs,
                    "summary":   "",
                    "_category": source_category,
                    "_tier":     source_meta.get("tier", 3),
                    "_asset_class": ASSET_CLASS_BY_CATEGORY.get(source_category, "crypto"),
                })
        except Exception as exc:
            # A single source's selector breaking (site redesign, etc.) must
            # not take down the whole scrape run — same fail-soft posture
            # used everywhere else in this file.
            print(f"[WARN] Failed to parse {source_meta['name']} listing: {exc}")
            continue

    return articles


# ---------------------------------------------------------------------------
# 3c. GEOPOLITICAL / DISASTER EVENTS (GDELT + USGS — structured, keyless APIs)
# ---------------------------------------------------------------------------
GDELT_QUERY_TERMS = ["war", "conflict", "sanctions", "invasion", "coup", "ceasefire"]
GDELT_TIMESPAN = "1h"   # GDELT rejects windows shorter than this ("Timespan is too short")
GDELT_MAX_RECORDS = 50


def classify_gdelt_tone(tone) -> tuple[str, float]:
    """Starting heuristic — GDELT docs cite -5..5 as the "typical" tone
    range; thresholds should be re-tuned against real observed values from a
    production run (the rate-limit issue below prevented sampling a live
    distribution during development)."""
    try:
        tone = float(tone)
    except (TypeError, ValueError):
        return "Neutral", 0.5
    if tone >= 1.5:
        return "Bullish", round(min(0.5 + abs(tone) / 20, 0.95), 4)
    if tone <= -1.5:
        return "Bearish", round(min(0.5 + abs(tone) / 20, 0.95), 4)
    return "Neutral", 0.5


def classify_usgs_magnitude(mag) -> tuple[str, float]:
    """Starting heuristic, not authoritative seismology — only large
    quakes are treated as market-relevant/risk-off."""
    try:
        mag = float(mag)
    except (TypeError, ValueError):
        return "Neutral", 0.5
    if mag >= 6.0:
        return "Bearish", round(min(0.5 + (mag - 6.0) / 8, 0.95), 4)
    return "Neutral", 0.5


def _fetch_gdelt_events() -> list[dict]:
    """GDELT DOC 2.0 API — free, keyless. Enforces a real (and, in testing,
    stricter-than-documented) rate limit — wrapped defensively so a 429/error
    here never breaks the run; treat GDELT as best-effort, not reliable."""
    query = " OR ".join(GDELT_QUERY_TERMS)
    params = {
        "query": f"({query}) sourcelang:eng",
        "mode": "artlist",
        "format": "json",
        "timespan": GDELT_TIMESPAN,
        "maxrecords": GDELT_MAX_RECORDS,
    }
    try:
        resp = requests.get(
            "https://api.gdeltproject.org/api/v2/doc/doc",
            params=params, timeout=8, headers=DEFAULT_HEADERS,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        print(f"  [WARN] GDELT fetch failed (best-effort source, continuing): {exc}")
        return []

    events = []
    for item in data.get("articles", []):
        title = (item.get("title") or "").strip()
        url = item.get("url") or ""
        if not title or not url:
            continue
        sentiment, confidence = classify_gdelt_tone(item.get("tone"))
        events.append({
            "title": title,
            "url": url,
            "source": item.get("domain") or "GDELT",
            "published": None,  # GDELT's seendate format needs its own parser; omit rather than guess
            "tickers": [],
            "currency_pairs": [],
            "summary": "",
            "_category": "GEOPOLITICS",
            "_tier": 2,
            "_asset_class": "geopolitics",
            "sentiment": sentiment,
            "confidence": confidence,
            "sentiment_engine": "gdelt_tone",
            "event_source": "gdelt",
            "is_crypto_relevant": True,
        })
    return events


def _fetch_usgs_events() -> list[dict]:
    """USGS Earthquake GeoJSON feed — free, keyless, confirmed stable."""
    try:
        resp = requests.get(
            "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson",
            timeout=8, headers=DEFAULT_HEADERS,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        print(f"  [WARN] USGS fetch failed: {exc}")
        return []

    events = []
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        title = (props.get("title") or "").strip()
        url = props.get("url") or ""
        if not title or not url:
            continue
        mag = props.get("mag")
        sentiment, confidence = classify_usgs_magnitude(mag)
        time_ms = props.get("time")
        published = None
        if time_ms:
            try:
                published = datetime.fromtimestamp(time_ms / 1000, tz=timezone.utc).isoformat()
            except Exception:
                published = None
        events.append({
            "title": title,
            "url": url,
            "source": "USGS",
            "published": published,
            "tickers": [],
            "currency_pairs": [],
            "summary": props.get("place") or "",
            "_category": "GEOPOLITICS",
            "_tier": 1,
            "_asset_class": "geopolitics",
            "sentiment": sentiment,
            "confidence": confidence,
            "sentiment_engine": "usgs_magnitude",
            "event_source": "usgs",
            "magnitude": mag,
            "is_crypto_relevant": True,
        })
    return events


def fetch_geopolitical_events() -> list[dict]:
    """Combines GDELT + USGS, each independently isolated so one API being
    down/rate-limited never blocks the other or the run."""
    events = []
    events.extend(_fetch_gdelt_events())
    events.extend(_fetch_usgs_events())
    # ACLED (armed-conflict event data) was considered but not implemented —
    # its free-tier registration terms need a separate feasibility check.
    return events


# ---------------------------------------------------------------------------
# 3d. X / TWITTER CASHTAG SEARCH (FxTwitter public mirror — free, keyless)
# ---------------------------------------------------------------------------
# Batched cashtag search rather than a fixed account watchlist — directly
# matches the actual need (tweets that mention a specific $TICKER, with the
# author's name and full tweet text), confirmed live against a real query
# during planning. No login, no official paid API, no persistent server.
#
# Quality note (found via live testing, not theoretical): unrestricted
# cashtag search on X is dominated by low-signal noise — presale/shill
# accounts, "top gainers" bot spam, airdrop-claim phishing patterns, and
# non-English pump chatter. A live A/B check of FxTwitter's "Top" vs default
# sort showed no meaningful difference (crypto-Twitter's cashtag firehose is
# just noisy by nature). Follower count proved a far more useful quality
# signal than like/repost counts, which were near-zero across nearly all
# results regardless of legitimacy (search results skew toward
# very-recently-posted tweets that haven't accumulated engagement yet).
X_CASHTAG_BATCH_SIZE = 6  # tickers per query; conservative starting point, tune after observing result relevance
X_MIN_FOLLOWERS = 10_000  # primary quality gate — filters the smallest shill/bot accounts
# Restrict to well-established tickers rather than the full ~500-symbol
# registry — small-cap/presale coins attracted disproportionately more
# pump/shill content in testing than majors like BTC/ETH/SOL.
X_MAJOR_TICKERS = [
    "BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "AVAX", "LINK", "DOT", "BNB",
    "MATIC", "LTC", "TRX", "TON", "ATOM", "UNI", "NEAR", "APT", "ARB", "OP",
]


def _build_cashtag_batches(tickers: list[str]) -> list[list[str]]:
    return [tickers[i:i + X_CASHTAG_BATCH_SIZE] for i in range(0, len(tickers), X_CASHTAG_BATCH_SIZE)]


def _looks_like_spam(text: str) -> bool:
    """Keyword layer on top of the follower-count gate — catches obvious
    scam/promo patterns even from accounts that clear the follower
    threshold (e.g. a compromised account posting a phishing link)."""
    text_lower = text.lower()
    spam_markers = [
        "t.me/", "join our telegram", "🎯 target", "🚀🚀🚀", "airdrop", "pump signal",
        "claim page", "claim your", "allocation is", "presale", "whitelist spot",
        "biggest daily gainers", "top gainers on", "morning bell", "24h  总市值",
    ]
    return any(marker in text_lower for marker in spam_markers)


def _is_mostly_non_latin(text: str) -> bool:
    """Cheap language filter — Snitch's sentiment engines (VADER's lexicon
    especially) are English-tuned, and non-Latin-script spam (Chinese/
    Russian/etc. bot accounts) was common in live cashtag-search testing.
    Not true language detection, just a fast heuristic: if most letters
    fall outside the basic Latin range, treat it as non-English."""
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 8:
        return False  # too short to judge, don't false-positive on cashtags/emoji-only tweets
    non_latin = sum(1 for c in letters if ord(c) > 0x24F)  # beyond extended Latin
    return (non_latin / len(letters)) > 0.3


def fetch_x_cashtags(coin_keywords: dict[str, list[str]]) -> list[dict]:
    """Search FxTwitter for tweets containing known crypto ticker cashtags,
    batched via OR queries to minimize request count. Restricted to major
    tickers and filtered by follower count + spam markers + language —
    see the quality note above for why (found via live testing)."""
    tickers = [t for t in X_MAJOR_TICKERS if t in coin_keywords]
    batches = _build_cashtag_batches(tickers)

    articles: list[dict] = []
    for batch in batches:
        query = " OR ".join(f"${t}" for t in batch)
        try:
            resp = requests.get(
                "https://api.fxtwitter.com/2/search",
                params={"q": query}, timeout=8, headers=DEFAULT_HEADERS,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            print(f"  [WARN] FxTwitter search failed for batch {batch}: {exc}")
            time.sleep(0.5)
            continue

        for item in data.get("results", []):
            text = (item.get("text") or "").strip()
            url = item.get("url") or ""
            if not text or not url:
                continue
            if _looks_like_spam(text) or _is_mostly_non_latin(text):
                continue

            author = item.get("author", {})
            if (author.get("followers") or 0) < X_MIN_FOLLOWERS:
                continue

            handle = author.get("screen_name") or author.get("name") or "unknown"
            tickers_found = extract_coin_tags(text, coin_keywords)
            if not tickers_found:
                continue  # matched the OR query on a substring but no clean ticker extracted

            created_ts = item.get("created_timestamp")
            published = None
            if created_ts:
                try:
                    published = datetime.fromtimestamp(created_ts, tz=timezone.utc).isoformat()
                except Exception:
                    published = None

            articles.append({
                "title":     text[:120],
                "url":       url,
                "source":    f"@{handle}",
                "published": published,
                "tickers":   tickers_found,
                "currency_pairs": [],
                "summary":   text[:300],
                "_category": "CRYPTO",
                "_tier":     3,  # individual tweets are inherently less vetted than curated RSS sources -> VADER-primary
                "_asset_class": "crypto",
                "source_type": "x",
                "likes":   item.get("likes"),
                "reposts": item.get("reposts"),
                "replies": item.get("replies"),
                "follower_count": author.get("followers"),
            })
        time.sleep(0.5)

    return articles


# ---------------------------------------------------------------------------
# 3b. MYFXBOOK COMMUNITY OUTLOOK (retail positioning sentiment)
# ---------------------------------------------------------------------------
# Official, documented, free myfxbook API — not scraping. Session-token auth,
# 100 req/24h free-tier cap, so this is gated to at most once/hour via the
# `forex_sentiment.updated_at` timestamp already committed in news.json (the
# same "read our own previous output" trick used for existing_articles).
MYFXBOOK_SENTIMENT_TTL_SECONDS = 60 * 60  # 1 hour
MYFXBOOK_SKEW_THRESHOLD = 80  # only pairs at >=80% long or short


def _myfxbook_login() -> Optional[str]:
    """Returns a session token, or None on any failure (fail-soft — never
    raises, since a missing/invalid account is an expected pre-launch state
    until the user creates one and adds MYFXBOOK_EMAIL/MYFXBOOK_PASSWORD)."""
    email = os.environ.get("MYFXBOOK_EMAIL", "")
    password = os.environ.get("MYFXBOOK_PASSWORD", "")
    if not email or not password:
        return None
    try:
        resp = requests.get(
            "https://www.myfxbook.com/api/login.json",
            params={"email": email, "password": password}, timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("error"):
            print(f"  [WARN] myfxbook login error: {data.get('message')}")
            return None
        return data.get("session")
    except Exception as exc:
        print(f"  [WARN] myfxbook login failed: {exc}")
        return None


def _myfxbook_get_outlook(session_token: str) -> Optional[list[dict]]:
    """Fetches community outlook pairs. On an expired/invalid session, re-logs
    in once and retries; gives up (returns None) if that also fails. Field
    names are read defensively (multiple plausible keys) since the exact
    live response shape hasn't been verified against real credentials yet —
    flagged as a follow-up verification step once the user has an account."""
    def _call(token: str):
        resp = requests.get(
            "https://www.myfxbook.com/api/get-community-outlook.json",
            params={"session": token}, timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    try:
        data = _call(session_token)
    except Exception as exc:
        print(f"  [WARN] myfxbook get-community-outlook failed: {exc}")
        return None

    if data.get("error"):
        # Expired/invalid session -> re-login once and retry.
        print(f"  [INFO] myfxbook session appears invalid ({data.get('message')}), re-authenticating…")
        new_token = _myfxbook_login()
        if not new_token:
            return None
        try:
            data = _call(new_token)
        except Exception as exc:
            print(f"  [WARN] myfxbook get-community-outlook retry failed: {exc}")
            return None
        if data.get("error"):
            print(f"  [WARN] myfxbook get-community-outlook still erroring after re-login: {data.get('message')}")
            return None

    pairs = data.get("symbols") or data.get("pairs") or data.get("data") or []
    return pairs if isinstance(pairs, list) else None


def fetch_forex_sentiment(old_data: dict) -> Optional[dict]:
    """Hourly-gated orchestrator. Returns the previous forex_sentiment dict
    unchanged if it's still fresh (or on any failure), never drops previously
    -good data, and never breaks the run if myfxbook is unreachable/not yet
    configured (expected pre-launch state)."""
    previous = old_data.get("forex_sentiment")
    if previous and previous.get("updated_at"):
        try:
            prev_dt = datetime.fromisoformat(previous["updated_at"])
            age = (datetime.now(timezone.utc) - prev_dt).total_seconds()
            if age < MYFXBOOK_SENTIMENT_TTL_SECONDS:
                return previous
        except Exception:
            pass

    token = _myfxbook_login()
    if not token:
        return previous  # not configured yet, or auth failed — keep last-known-good

    raw_pairs = _myfxbook_get_outlook(token)
    if raw_pairs is None:
        return previous

    skewed = []
    for p in raw_pairs:
        try:
            long_pct = float(p.get("longPercentage") if p.get("longPercentage") is not None else p.get("long_pct", 0))
            short_pct = float(p.get("shortPercentage") if p.get("shortPercentage") is not None else p.get("short_pct", 0))
        except (TypeError, ValueError):
            continue
        if long_pct < MYFXBOOK_SKEW_THRESHOLD and short_pct < MYFXBOOK_SKEW_THRESHOLD:
            continue
        long_vol = p.get("longVolume", p.get("long_volume_lots", 0)) or 0
        short_vol = p.get("shortVolume", p.get("short_volume_lots", 0)) or 0
        skewed.append({
            "symbol": p.get("name") or p.get("symbol"),
            "short_pct": short_pct,
            "long_pct": long_pct,
            "short_volume_lots": short_vol,
            "long_volume_lots": long_vol,
            "short_positions": p.get("shortPositions", p.get("short_positions")),
            "long_positions": p.get("longPositions", p.get("long_positions")),
            "_total_volume": float(long_vol or 0) + float(short_vol or 0),
        })

    # Popularity rank derived client-side from total volume relative to the
    # max in the filtered set, unless the live API already provides a
    # popularity/ranking field (none of the plausible field names above
    # include one — verify against real data once credentials exist).
    if skewed:
        max_vol = max(s["_total_volume"] for s in skewed) or 1
        skewed.sort(key=lambda s: s["_total_volume"], reverse=True)
        for i, s in enumerate(skewed):
            s["popularity_rank"] = i + 1
            del s["_total_volume"]

    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "pairs": skewed,
    }


# ---------------------------------------------------------------------------
# 3c. MACRO SNAPSHOT (FMP primary, Alpha Vantage fallback)
# ---------------------------------------------------------------------------
# Treasury yields / Fed funds / CPI / GDP barely move intraday — fetched at
# most once/day, gated the same way as forex_sentiment (read our own prior
# output's updated_at back from news.json).
FMP_STABLE_BASE = "https://financialmodelingprep.com/stable"
ALPHA_VANTAGE_BASE = "https://www.alphavantage.co/query"
TWELVE_DATA_BASE = "https://api.twelvedata.com"
API_NINJAS_BASE = "https://api.api-ninjas.com/v1"


def _fetch_macro_fmp() -> Optional[dict]:
    api_key = os.environ.get("FMP_API_KEY", "")
    if not api_key:
        return None
    try:
        treasury = requests.get(f"{FMP_STABLE_BASE}/treasury-rates", params={"apikey": api_key}, timeout=10)
        treasury.raise_for_status()
        treasury_data = treasury.json()
        t0 = treasury_data[0] if isinstance(treasury_data, list) and treasury_data else {}

        econ = requests.get(
            f"{FMP_STABLE_BASE}/economic-indicators",
            params={"name": "federalFunds", "apikey": api_key}, timeout=10,
        )
        econ.raise_for_status()
        econ_data = econ.json()
        e0 = econ_data[0] if isinstance(econ_data, list) and econ_data else {}

        risk_premium = requests.get(f"{FMP_STABLE_BASE}/market-risk-premium", params={"apikey": api_key}, timeout=10)
        risk_premium.raise_for_status()
        rp_data = risk_premium.json()
        rp0 = rp_data[0] if isinstance(rp_data, list) and rp_data else {}

        snapshot = {
            "treasury_yield_10y": t0.get("year10"),
            "fed_funds_rate": e0.get("value"),
            "market_risk_premium": rp0.get("totalEquityRiskPremium") or rp0.get("marketRiskPremium"),
            # CPI/GDP/unemployment/nonfarm payroll field names on FMP's
            # "economic-indicators" endpoint need a live-data verification
            # pass once the key is confirmed working — left null until then.
            "cpi_yoy": None,
            "gdp_real": None,
            "unemployment_rate": None,
            "nonfarm_payroll": None,
        }
        if all(v is None for v in snapshot.values()):
            return None
        return snapshot
    except Exception as exc:
        print(f"  [WARN] FMP macro fetch failed: {exc}")
        return None


def _fetch_macro_alpha_vantage() -> Optional[dict]:
    """Fallback only — called exclusively when FMP fails, to respect Alpha
    Vantage's much tighter ~25 req/day free-tier quota."""
    api_key = os.environ.get("ALPHA_VANTAGE_API_KEY", "")
    if not api_key:
        return None

    def _latest_value(function: str, extra_params: dict | None = None) -> Optional[str]:
        params = {"function": function, "apikey": api_key}
        if extra_params:
            params.update(extra_params)
        resp = requests.get(ALPHA_VANTAGE_BASE, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        series = data.get("data")
        if isinstance(series, list) and series:
            return series[0].get("value")
        return None

    try:
        snapshot = {
            "treasury_yield_10y": _latest_value("TREASURY_YIELD", {"interval": "daily", "maturity": "10year"}),
            "fed_funds_rate": _latest_value("FEDERAL_FUNDS_RATE", {"interval": "daily"}),
            "cpi_yoy": _latest_value("CPI", {"interval": "monthly"}),
            "gdp_real": _latest_value("REAL_GDP", {"interval": "quarterly"}),
            "unemployment_rate": _latest_value("UNEMPLOYMENT"),
            "nonfarm_payroll": _latest_value("NONFARM_PAYROLL"),
            "market_risk_premium": None,
        }
        if all(v is None for v in snapshot.values()):
            return None
        return snapshot
    except Exception as exc:
        print(f"  [WARN] Alpha Vantage macro fetch failed: {exc}")
        return None


def fetch_macro_snapshot(old_data: dict) -> Optional[dict]:
    """Daily-gated orchestrator: FMP primary, Alpha Vantage fallback-only.
    Keeps the previous snapshot (flagged stale) rather than dropping it if
    both providers fail on a given day."""
    previous = old_data.get("macro_snapshot")
    today = datetime.now(timezone.utc).date().isoformat()
    if previous and previous.get("updated_at", "").startswith(today):
        return previous  # already fetched today

    fmp_result = _fetch_macro_fmp()
    if fmp_result is not None:
        print("  [INFO] macro_snapshot: using FMP (primary)")
        return {"updated_at": datetime.now(timezone.utc).isoformat(), "source": "fmp", **fmp_result}

    av_result = _fetch_macro_alpha_vantage()
    if av_result is not None:
        print("  [INFO] macro_snapshot: FMP failed, using Alpha Vantage (fallback)")
        return {"updated_at": datetime.now(timezone.utc).isoformat(), "source": "alpha_vantage", **av_result}

    print("  [WARN] macro_snapshot: both FMP and Alpha Vantage failed, keeping previous snapshot (stale)")
    if previous:
        return {**previous, "stale": True}
    return None


# ---------------------------------------------------------------------------
# 3d. COMMODITY SNAPSHOT (Twelve Data primary, FMP + Alpha Vantage fallback)
# — replaces an earlier Stooq-based plan; Stooq turned out to be blocked by
# a Cloudflare bot-challenge on every request (browser and server-side
# alike), confirmed via live testing. FMP's commodity quotes then turned out
# to be gated behind a 402 on the current plan (confirmed live), and Alpha
# Vantage has no working gold/silver source at all (its CURRENCY_EXCHANGE_RATE
# doesn't actually support XAU/XAG despite that being a commonly-cited
# trick). Twelve Data's free tier (800 credits/day, 8 req/min) covers
# indices, commodities, and metals in one place, so it's now primary for
# both commodity_snapshot and index_snapshot. Same daily-gate pattern as
# fetch_macro_snapshot throughout.
# ---------------------------------------------------------------------------
# Twelve Data's free tier turned out (confirmed via live testing, including
# its own /symbol_search endpoint) to only cover equities/ETFs — raw index
# symbols (SPX/DJI/etc.) and raw commodity symbols (WTI/USD, XAU/USD, etc.)
# all came back "not available with your plan" or "not found", the same
# practical limitation Finnhub already has on its free tier. Twelve Data's
# commodity rows use well-known US-listed ETF proxies instead.
#
# API Ninjas (added later, 3000 req/month free tier) has a real Commodity
# Price API with actual spot prices (not ETF proxies) for exactly these six,
# so it's now PRIMARY for commodity_snapshot — Twelve Data's ETF-proxy
# numbers are the fallback. Each entry below carries every provider's own
# symbol/name convention; `symbol`/`label` are the stable, provider-agnostic
# identifiers used in the output regardless of which provider answered.
COMMODITY_WATCHLIST = [
    {"symbol": "CRUDE_OIL", "label": "Crude Oil (WTI)", "fmp_symbol": "CLUSD", "twelvedata_symbol": "USO", "apininja_name": "crude_oil"},
    {"symbol": "BRENT_CRUDE", "label": "Brent Crude", "fmp_symbol": "BZUSD", "twelvedata_symbol": "BNO", "apininja_name": "brent_crude_oil"},
    {"symbol": "GOLD", "label": "Gold", "fmp_symbol": "GCUSD", "twelvedata_symbol": "GLD", "apininja_name": "gold"},
    {"symbol": "SILVER", "label": "Silver", "fmp_symbol": "SIUSD", "twelvedata_symbol": "SLV", "apininja_name": "silver"},
    {"symbol": "NATURAL_GAS", "label": "Natural Gas", "fmp_symbol": "NGUSD", "twelvedata_symbol": "UNG", "apininja_name": "natural_gas"},
    {"symbol": "COPPER", "label": "Copper", "fmp_symbol": "HGUSD", "twelvedata_symbol": "CPER", "apininja_name": "copper"},
]


def _fetch_commodities_apininja(previous_prices: dict) -> Optional[list[dict]]:
    """PRIMARY commodity source: API Ninjas' Commodity Price API returns a
    real current spot price per commodity `name` (one request each — no
    batch endpoint), but no % change field, so day-over-day change is
    computed here from yesterday's stored price for the same canonical
    `symbol` (whichever provider supplied it) — same "read our own previous
    output" idiom used elsewhere in this project. `previous_prices` is
    {symbol: price} from the last successful commodity_snapshot."""
    api_key = os.environ.get("API_NINJAS_KEY", "")
    if not api_key:
        return None
    try:
        items = []
        for watch in COMMODITY_WATCHLIST:
            resp = requests.get(
                f"{API_NINJAS_BASE}/commodityprice",
                params={"name": watch["apininja_name"]},
                headers={"X-Api-Key": api_key}, timeout=10,
            )
            if not resp.ok:
                print(f"  [WARN] API Ninjas {watch['apininja_name']}: HTTP {resp.status_code} — {resp.text[:150]}")
                continue
            data = resp.json()
            price = data.get("price")
            if price is None:
                print(f"  [WARN] API Ninjas {watch['apininja_name']}: no price in response ({data})")
                continue
            price = float(price)
            prev_price = previous_prices.get(watch["symbol"])
            pct = ((price - prev_price) / prev_price) * 100 if prev_price else None
            items.append({"symbol": watch["symbol"], "label": watch["label"], "price": price, "changes_percentage": pct})
        return items if items else None
    except Exception as exc:
        print(f"  [WARN] API Ninjas commodities fetch failed: {exc}")
        return None

INDICES_WATCHLIST = [
    {"symbol": "SPY", "label": "S&P 500 (SPY)"},
    {"symbol": "QQQ", "label": "Nasdaq 100 (QQQ)"},
    {"symbol": "DIA", "label": "Dow Jones (DIA)"},
    {"symbol": "IWM", "label": "Russell 2000 (IWM)"},
    {"symbol": "VIXY", "label": "Volatility (VIXY)"},
]


def _twelvedata_quote_batch(symbols: list[str]) -> Optional[dict]:
    """Twelve Data's /quote endpoint accepts a comma-joined symbol batch and
    returns either a single quote object (one symbol) or a dict keyed by
    symbol (multiple) — handled defensively here since the exact response
    shape per symbol *category* (indices vs. commodities vs. equities)
    hasn't been verified against a live multi-symbol response, only single-
    symbol equity quotes (confirmed field names: close/previous_close/
    percent_change). Returns {symbol: quote_dict}, or None on failure."""
    api_key = os.environ.get("TWELVE_DATA_API_KEY", "")
    if not api_key:
        return None
    try:
        resp = requests.get(
            f"{TWELVE_DATA_BASE}/quote",
            params={"symbol": ",".join(symbols), "apikey": api_key}, timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and "symbol" in data:
            return {data["symbol"]: data}  # single-symbol response shape
        if isinstance(data, dict):
            # Multi-symbol shape: {"SYM1": {...}, "SYM2": {...}}, filter out
            # any per-symbol error entries (e.g. {"code": 400, "status": "error"}),
            # logging what actually went wrong per symbol for live diagnosis.
            good = {}
            for sym, q in data.items():
                if isinstance(q, dict) and q.get("status") != "error":
                    good[sym] = q
                elif isinstance(q, dict):
                    print(f"  [WARN] Twelve Data {sym}: {q.get('message') or q}")
            return good
        return None
    except Exception as exc:
        print(f"  [WARN] Twelve Data quote batch failed: {exc}")
        return None


def _fetch_commodities_twelvedata() -> Optional[list[dict]]:
    symbol_map = {c["twelvedata_symbol"]: c for c in COMMODITY_WATCHLIST}
    quotes = _twelvedata_quote_batch(list(symbol_map.keys()))
    if not quotes:
        return None
    items = []
    for td_symbol, watch in symbol_map.items():
        q = quotes.get(td_symbol)
        if not q:
            continue
        try:
            price = float(q["close"])
        except (KeyError, ValueError, TypeError):
            continue
        pct = q.get("percent_change")
        try:
            pct = float(pct) if pct is not None else None
        except (ValueError, TypeError):
            pct = None
        items.append({"symbol": watch["symbol"], "label": watch["label"], "price": price, "changes_percentage": pct})
    return items if items else None


def fetch_index_snapshot(old_data: dict) -> Optional[dict]:
    """Daily-gated, Twelve Data only — moves index quotes server-side so the
    Indices tile row doesn't depend on a client-embedded FINNHUB_API_KEY
    (which the free-tier Finnhub path in index.html still needs separately
    for the equities Top Gainers/Losers table under that row)."""
    previous = old_data.get("index_snapshot")
    today = datetime.now(timezone.utc).date().isoformat()
    if previous and previous.get("updated_at", "").startswith(today):
        return previous

    symbols = [i["symbol"] for i in INDICES_WATCHLIST]
    quotes = _twelvedata_quote_batch(symbols)
    if quotes:
        items = []
        for watch in INDICES_WATCHLIST:
            q = quotes.get(watch["symbol"])
            if not q:
                continue
            try:
                price = float(q["close"])
            except (KeyError, ValueError, TypeError):
                continue
            pct = q.get("percent_change")
            try:
                pct = float(pct) if pct is not None else None
            except (ValueError, TypeError):
                pct = None
            items.append({"symbol": watch["symbol"], "label": watch["label"], "price": price, "changes_percentage": pct})
        if items:
            print("  [INFO] index_snapshot: using Twelve Data")
            return {"updated_at": datetime.now(timezone.utc).isoformat(), "source": "twelvedata", "items": items}

    print("  [WARN] index_snapshot: Twelve Data failed, keeping previous snapshot (stale)")
    if previous:
        return {**previous, "stale": True}
    return None


def _fetch_commodities_fmp() -> Optional[list[dict]]:
    """FMP's /stable/quote endpoint accepts a comma-joined symbol batch.
    Exact commodity ticker conventions (CLUSD/BZUSD/GCUSD/etc.) are FMP's
    documented commodity symbols as of this writing — verify against a live
    response once FMP_API_KEY is set, same caveat already applied to the
    macro_snapshot/forex_sentiment field-name assumptions in this project."""
    api_key = os.environ.get("FMP_API_KEY", "")
    if not api_key:
        return None
    try:
        symbols = ",".join(item["fmp_symbol"] for item in COMMODITY_WATCHLIST)
        resp = requests.get(
            f"{FMP_STABLE_BASE}/quote",
            params={"symbol": symbols, "apikey": api_key}, timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list) or not data:
            return None
        by_symbol = {row.get("symbol"): row for row in data}
        items = []
        for watch in COMMODITY_WATCHLIST:
            row = by_symbol.get(watch["fmp_symbol"])
            if not row:
                continue
            items.append({
                "symbol": watch["symbol"],
                "label": watch["label"],
                "price": row.get("price"),
                "changes_percentage": row.get("changesPercentage"),
            })
        return items if items else None
    except Exception as exc:
        print(f"  [WARN] FMP commodities fetch failed: {exc}")
        return None


_METALS_WATCHLIST = [
    {"symbol": "GOLD", "label": "Gold", "fmp_forex_symbol": "XAUUSD"},
    {"symbol": "SILVER", "label": "Silver", "fmp_forex_symbol": "XAGUSD"},
]


def _fetch_metals_fmp() -> Optional[list[dict]]:
    """Gold/silver specifically: FMP's plain /stable/quote commodity symbols
    (GCUSD/SIUSD) are gated behind the same 402 as the other commodities on
    the current plan, and Alpha Vantage's CURRENCY_EXCHANGE_RATE doesn't
    actually support XAU/XAG despite that being a commonly-cited trick
    (confirmed live: "Invalid API call"). FMP also quotes precious metals as
    forex-style pairs (XAUUSD/XAGUSD) via the same /stable/quote endpoint —
    worth trying since forex quotes are typically a different (often lower)
    plan tier than commodities; verify against a live response, same caveat
    as the rest of this project's FMP field-name assumptions."""
    api_key = os.environ.get("FMP_API_KEY", "")
    if not api_key:
        return None
    try:
        symbols = ",".join(m["fmp_forex_symbol"] for m in _METALS_WATCHLIST)
        resp = requests.get(
            f"{FMP_STABLE_BASE}/quote",
            params={"symbol": symbols, "apikey": api_key}, timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list) or not data:
            return None
        by_symbol = {row.get("symbol"): row for row in data}
        items = []
        for m in _METALS_WATCHLIST:
            row = by_symbol.get(m["fmp_forex_symbol"])
            if not row:
                continue
            items.append({
                "symbol": m["symbol"],
                "label": m["label"],
                "price": row.get("price"),
                "changes_percentage": row.get("changesPercentage"),
            })
        return items if items else None
    except Exception as exc:
        print(f"  [WARN] FMP metals (forex-style) fetch failed: {exc}")
        return None


def _fetch_commodities_alpha_vantage() -> Optional[list[dict]]:
    """Fallback for when FMP's commodity quotes aren't available on the
    user's plan (confirmed via live testing: FMP's /stable/quote returns
    402 Payment Required for commodity symbols on the free tier). Alpha
    Vantage has real, documented endpoints for WTI/BRENT/NATURAL_GAS/COPPER
    (time series, % change derived from the two most recent points) and
    treats gold/silver as currency pairs via CURRENCY_EXCHANGE_RATE (spot
    rate only, no historical point in that same call, so no % change for
    those two — the frontend already renders tiles fine without one)."""
    api_key = os.environ.get("ALPHA_VANTAGE_API_KEY", "")
    if not api_key:
        return None

    def _series_quote(function: str) -> tuple[Optional[float], Optional[float]]:
        resp = requests.get(ALPHA_VANTAGE_BASE, params={"function": function, "interval": "daily", "apikey": api_key}, timeout=10)
        resp.raise_for_status()
        body = resp.json()
        series = body.get("data")
        if not isinstance(series, list) or len(series) < 1:
            # Free tier is capped at 5 req/min — a "Note"/"Information" field
            # here (instead of "data") almost always means we got rate-limited
            # mid-batch, not that the symbol/endpoint is wrong.
            note = body.get("Note") or body.get("Information") or body
            print(f"  [WARN] Alpha Vantage {function}: no data series ({str(note)[:150]})")
            return None, None
        try:
            latest = float(series[0]["value"])
        except (KeyError, ValueError, TypeError):
            return None, None
        if len(series) < 2:
            return latest, None
        try:
            prev = float(series[1]["value"])
            pct = ((latest - prev) / prev) * 100 if prev else None
        except (KeyError, ValueError, TypeError, ZeroDivisionError):
            pct = None
        return latest, pct

    def _metal_quote(currency_code: str) -> Optional[float]:
        resp = requests.get(ALPHA_VANTAGE_BASE, params={
            "function": "CURRENCY_EXCHANGE_RATE", "from_currency": currency_code,
            "to_currency": "USD", "apikey": api_key,
        }, timeout=10)
        resp.raise_for_status()
        body = resp.json()
        rate = body.get("Realtime Currency Exchange Rate", {}).get("5. Exchange Rate")
        if rate is None:
            note = body.get("Note") or body.get("Information") or body
            print(f"  [WARN] Alpha Vantage {currency_code}/USD: no exchange rate ({str(note)[:150]})")
            return None
        try:
            return float(rate)
        except (ValueError, TypeError):
            return None

    try:
        items = []
        calls = [
            (COMMODITY_WATCHLIST[0], "series", "WTI"),
            (COMMODITY_WATCHLIST[1], "series", "BRENT"),
            (COMMODITY_WATCHLIST[4], "series", "NATURAL_GAS"),
            (COMMODITY_WATCHLIST[5], "series", "COPPER"),
            (COMMODITY_WATCHLIST[2], "metal", "XAU"),
            (COMMODITY_WATCHLIST[3], "metal", "XAG"),
        ]
        # Free tier caps at 5 req/min — space calls out so a 6-call batch
        # (well under the 25/day cap since this only runs once daily) never
        # trips the per-minute limit.
        for i, (watch, kind, param) in enumerate(calls):
            if i > 0:
                time.sleep(15)
            if kind == "series":
                price, pct = _series_quote(param)
            else:
                price, pct = _metal_quote(param), None
            if price is not None:
                items.append({"symbol": watch["symbol"], "label": watch["label"], "price": price, "changes_percentage": pct})

        return items if items else None
    except Exception as exc:
        print(f"  [WARN] Alpha Vantage commodities fetch failed: {exc}")
        return None


def fetch_commodity_snapshot(old_data: dict) -> Optional[dict]:
    """Daily-gated, per-symbol merge across providers in priority order —
    NOT all-or-nothing per provider, since API Ninjas' free tier only
    covers a rotating weekly subset of commodities (confirmed live: only
    Gold was free the week this was tested, the other 5 came back "premium
    users only") and treating that partial success as "done" would silently
    drop the rest instead of falling through to a provider that has them.
    Priority per commodity: API Ninjas (real spot price, no % change field
    so that's computed from yesterday's stored price for the same symbol)
    → Twelve Data (ETF proxy) → FMP (ETF-adjacent commodity ticker, or
    forex-style XAUUSD/XAGUSD for metals) → Alpha Vantage (energy/copper
    only, no gold/silver support at all). Keeps the previous snapshot
    (flagged stale) if every provider fails for every symbol today."""
    previous = old_data.get("commodity_snapshot")
    today = datetime.now(timezone.utc).date().isoformat()
    if previous and previous.get("updated_at", "").startswith(today):
        return previous

    previous_prices = {i["symbol"]: i.get("price") for i in (previous or {}).get("items", [])}

    by_symbol: dict[str, dict] = {}
    sources_used: set[str] = set()

    def _absorb(items: Optional[list[dict]], source_name: str):
        for item in (items or []):
            sym = item.get("symbol")
            if sym and sym not in by_symbol:
                by_symbol[sym] = item
                sources_used.add(source_name)

    _absorb(_fetch_commodities_apininja(previous_prices), "api_ninjas")
    if len(by_symbol) < len(COMMODITY_WATCHLIST):
        _absorb(_fetch_commodities_twelvedata(), "twelvedata")
    if len(by_symbol) < len(COMMODITY_WATCHLIST):
        _absorb(_fetch_commodities_fmp(), "fmp")
        _absorb(_fetch_metals_fmp(), "fmp")
    if len(by_symbol) < len(COMMODITY_WATCHLIST):
        _absorb(_fetch_commodities_alpha_vantage(), "alpha_vantage")

    if by_symbol:
        items = [by_symbol[w["symbol"]] for w in COMMODITY_WATCHLIST if w["symbol"] in by_symbol]
        source = "+".join(sorted(sources_used))
        print(f"  [INFO] commodity_snapshot: {len(items)}/{len(COMMODITY_WATCHLIST)} symbols via {source}")
        return {"updated_at": datetime.now(timezone.utc).isoformat(), "source": source, "items": items}

    print("  [WARN] commodity_snapshot: all providers failed, keeping previous snapshot (stale)")
    if previous:
        return {**previous, "stale": True}
    return None


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
            story = {
                "title":        article["title"],
                "url":          article["url"],
                "source":       article["source"],
                "published":    article["published"],
                "tickers":      article["tickers"],
                "currency_pairs": article.get("currency_pairs", []),
                "summary":      article.get("summary", ""),
                # Preserve pre-computed sentiment (GDELT/USGS set these at
                # fetch time via deterministic mappings, not a text model —
                # overwriting with None here would discard that work).
                "sentiment":    article.get("sentiment"),
                "confidence":   article.get("confidence"),
                "other_sources": [],
                "category":     article.get("_category", "CRYPTO"),
                "region":       "GLOBAL",
                "asset_class":  article.get("_asset_class", "crypto"),
                "source_flag":  SOURCE_FLAGS.get(article["source"]),
                "sentiment_engine": article.get("sentiment_engine"),
                "source_type":  article.get("source_type", "rss"),
                "_tier":        article.get("_tier", 3),
            }
            # Additive, source-specific fields — only present when relevant,
            # never introduced as null noise on ordinary RSS articles.
            if "event_source" in article:
                story["event_source"] = article["event_source"]
            if "magnitude" in article:
                story["magnitude"] = article["magnitude"]
            if article.get("source_type") == "x":
                story["likes"] = article.get("likes")
                story["reposts"] = article.get("reposts")
                story["replies"] = article.get("replies")
                story["follower_count"] = article.get("follower_count")
            primary.append(story)

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
# 6b. FINBERT (forex/stocks primary engine)
# ---------------------------------------------------------------------------
# Optional dependency, same graceful-degradation pattern as VADER above —
# torch/transformers must never become a hard requirement that breaks the
# script if unavailable (e.g. not installed, or the model fails to download).
try:
    from transformers import pipeline as _hf_pipeline
    _finbert_classifier = _hf_pipeline("sentiment-analysis", model="ProsusAI/finbert")
    _FINBERT_AVAILABLE = True
except Exception as exc:
    print(f"  [WARN] FinBERT unavailable ({exc}). Forex/stocks will fall back to VADER/keyword.")
    _finbert_classifier = None
    _FINBERT_AVAILABLE = False

_FINBERT_LABEL_MAP = {"positive": "Bullish", "negative": "Bearish", "neutral": "Neutral"}

# Logs every FinBERT classification for future VADER-lexicon calibration
# (a separate, later task — this only accumulates the training data it would
# need). Append-only, one JSON object per line; committed by GH Actions
# alongside news.json/news.js/token_usage.json so it persists across runs.
FINBERT_TRAINING_LOG_FILE = os.path.join(os.path.dirname(__file__), "finbert_training_log.jsonl")


def classify_with_finbert(text: str) -> tuple[str, float]:
    # FinBERT's tokenizer truncates internally, but capping the raw string
    # keeps tokenization fast and avoids pathologically long summaries.
    result = _finbert_classifier(text[:2000], truncation=True, max_length=512)[0]
    sentiment = _FINBERT_LABEL_MAP.get(result["label"].lower(), "Neutral")
    confidence = round(float(result["score"]), 4)
    return sentiment, confidence


def _log_finbert_classification(article: dict, sentiment: str, confidence: float) -> None:
    """Best-effort append; a logging failure must never break the scrape run."""
    try:
        record = {
            "headline": article["title"],
            "summary": article.get("summary", ""),
            "finbert_label": sentiment,
            "finbert_score": confidence,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with open(FINBERT_TRAINING_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        print(f"  [WARN] Failed to append to FinBERT training log: {exc}")


def classify_fx_stock(articles: list[dict]) -> None:
    """
    Forex/stocks primary engine chain: FinBERT (its Reuters/earnings-style
    training distribution fits this content far better than Groq's
    crypto-tuned prompt) -> classify_fallback()'s VADER/keyword chain on
    FinBERT unavailability or a per-article error. Runs regardless of source
    tier — unlike crypto, forex/stocks doesn't route any of this through Groq.
    """
    if not _FINBERT_AVAILABLE:
        for a in articles:
            classify_fallback(a)
        return

    for a in articles:
        try:
            # FinBERT is classified on the title alone, not title+summary —
            # verified empirically (not assumed) that appending the summary
            # measurably hurts it here: e.g. one real headline flipped from
            # confident Positive (0.78) to uncertain Neutral (0.37) once a
            # one-sentence summary was appended, and another kept its label
            # but confidence collapsed from 0.82 to 0.47. Matches FinBERT's
            # actual training data (Financial PhraseBank — short single
            # financial statements, not headline+summary concatenations).
            combined_text = f"{a['title']}. {a.get('summary', '')}"
            sentiment, confidence = classify_with_finbert(a["title"])
            a["sentiment"] = sentiment
            a["confidence"] = confidence
            a["is_crypto_relevant"] = True
            a["sentiment_engine"] = "finbert"
            # FinBERT doesn't return category/region the way Groq does —
            # same heuristic inference classify_fallback() already uses.
            # Category/region inference benefits from the fuller text, so
            # this (unlike the sentiment call above) still uses title+summary.
            a["category"] = infer_category(combined_text, a.get("category", "CRYPTO"))
            a["region"] = infer_region(combined_text)
            _log_finbert_classification(a, sentiment, confidence)
        except Exception as exc:
            print(f"  [WARN] FinBERT classification error on one article: {exc}. Falling back to VADER.")
            classify_fallback(a)


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


def classify_crypto(articles: list[dict]) -> None:
    """
    Crypto sentiment routing — tiered by source prestige, unchanged from
    the pre-FinBERT design:
      - Tier 1/2 sources -> Groq primary, VADER fallback (rate limit/budget/error).
      - Tier 3/4 sources -> VADER primary by design (not just a fallback).
      - VADER unavailable -> keyword scorer as final fallback, any tier.
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
        print("[WARN] GROQ_API_KEY not set — all crypto articles will route to VADER/keyword engines.")

    usage = _load_token_usage()
    print(f"  Groq token usage today: {usage['tokens_used']}/{DAILY_TOKEN_LIMIT} "
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


def classify_sentiments(articles: list[dict]) -> list[dict]:
    """
    Dual sentiment pipeline, routed by asset_class (not by tier):
      - crypto          -> classify_crypto() — Groq/VADER tiered as before.
      - forex/stocks     -> classify_fx_stock() — FinBERT primary regardless
                             of tier, VADER/keyword fallback.
    Tags every article with which engine actually classified it via
    `sentiment_engine` ("groq" | "finbert" | "vader" | "keyword").
    """
    crypto_articles = [a for a in articles if a.get("asset_class", "crypto") == "crypto"]
    geo_event_articles = [a for a in articles if a.get("asset_class") == "geopolitics"]
    fx_stock_articles = [
        a for a in articles
        if a.get("asset_class", "crypto") not in ("crypto", "geopolitics")
    ]

    if crypto_articles:
        classify_crypto(crypto_articles)
    if fx_stock_articles:
        classify_fx_stock(fx_stock_articles)
    if geo_event_articles:
        classify_geo_events(geo_event_articles)

    print("✓ All sentiment classifications completed.")
    return articles


# ---------------------------------------------------------------------------
# 7b. GEOPOLITICAL EVENT CLASSIFICATION (deterministic, no text-sentiment model)
# ---------------------------------------------------------------------------
def classify_geo_events(articles: list[dict]) -> None:
    """
    GDELT/USGS events already carry their own purpose-built signal (GDELT's
    article `tone`, USGS's earthquake `mag`) computed at fetch time in
    fetch_geopolitical_events() — neither Groq nor FinBERT is trained on
    structured event records, so routing them through a text-sentiment model
    would add noise, not information. This function is mostly a no-op pass:
    it only fills in a Neutral default for the rare case an event slipped
    through without a pre-computed sentiment (defensive, not expected).
    """
    for a in articles:
        if a.get("sentiment_engine"):
            continue  # already scored deterministically at fetch time
        a["sentiment"] = "Neutral"
        a["confidence"] = 0.5
        a["sentiment_engine"] = a.get("event_source", "geo_event")
        a["is_crypto_relevant"] = True


# ---------------------------------------------------------------------------
# 8. MAIN
# ---------------------------------------------------------------------------
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "news.json")


def main():
    print(f"[{datetime.now().isoformat()}] Fetching CoinGecko coin registry…")
    coin_keywords = fetch_top_500_coingecko()

    # 1. Read existing articles (and prior forex_sentiment/macro_snapshot
    # snapshots) from news.json (if present) — this file is the only durable
    # state between runs, so hourly/daily gates for new fetches read their
    # own previous output back from here rather than an external cache.
    existing_articles = []
    old_data = {}
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

    print(f"[{datetime.now().isoformat()}] Fetching non-RSS sources (Scrapling)…")
    scrapling_articles = fetch_scrapling_sources(coin_keywords)
    print(f"  → {len(scrapling_articles)} articles fetched.")
    raw.extend(scrapling_articles)

    print(f"[{datetime.now().isoformat()}] Fetching geopolitical/disaster events (GDELT + USGS)…")
    geo_events = fetch_geopolitical_events()
    print(f"  → {len(geo_events)} events fetched.")
    raw.extend(geo_events)

    print(f"[{datetime.now().isoformat()}] Fetching X/Twitter cashtag search…")
    x_articles = fetch_x_cashtags(coin_keywords)
    print(f"  → {len(x_articles)} tweets fetched.")
    raw.extend(x_articles)

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
            story["asset_class"] = existing_story.get("asset_class", story.get("asset_class", "crypto"))
            story["currency_pairs"] = existing_story.get("currency_pairs", story.get("currency_pairs", []))
            story["source_type"] = existing_story.get("source_type", story.get("source_type", "rss"))
            # Additive, source-specific fields — only carry forward if either
            # side actually has them, never introduce null noise.
            for extra_field in ("event_source", "magnitude", "likes", "reposts", "replies", "follower_count"):
                if extra_field in existing_story:
                    story[extra_field] = existing_story[extra_field]
                elif extra_field in story:
                    pass  # keep the freshly-fetched value (e.g. updated like/repost counts)
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

    print(f"[{datetime.now().isoformat()}] Checking forex sentiment (myfxbook, hourly-gated)…")
    forex_sentiment = fetch_forex_sentiment(old_data)

    print(f"[{datetime.now().isoformat()}] Checking macro snapshot (FMP/Alpha Vantage, daily-gated)…")
    macro_snapshot = fetch_macro_snapshot(old_data)

    print(f"[{datetime.now().isoformat()}] Checking commodity snapshot (Twelve Data/FMP/Alpha Vantage, daily-gated)…")
    commodity_snapshot = fetch_commodity_snapshot(old_data)

    # Twelve Data's free tier counts each symbol in a batched /quote call
    # toward its 8-req/min cap — the commodities batch (6 symbols) can
    # already consume most of that window, so pause before the indices
    # batch (5 more) to avoid a 429 (confirmed happening back-to-back via
    # live testing). Both calls are daily-gated so this only costs time on
    # the one run/day that actually fetches live.
    time.sleep(65)

    print(f"[{datetime.now().isoformat()}] Checking index snapshot (Twelve Data, daily-gated)…")
    index_snapshot = fetch_index_snapshot(old_data)

    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total":      len(final),
        "articles":   final,
        "forex_sentiment": forex_sentiment,
        "macro_snapshot":  macro_snapshot,
        "commodity_snapshot": commodity_snapshot,
        "index_snapshot": index_snapshot,
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
