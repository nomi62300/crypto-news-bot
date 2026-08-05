#!/usr/bin/env python3
from __future__ import annotations
"""
fetch_news.py
-------------
Fetches crypto news from 30+ RSS feeds, deduplicates titles with fuzzy matching,
classifies sentiment via Hugging Face FinBERT (ProsusAI/finbert), and writes
the result to news.json.
"""

import json
import os
import re
import time
import socket
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher

from typing import Optional
import feedparser
import requests
import urllib3.util.connection as urllib3_cn

# ---------------------------------------------------------------------------
# CUSTOM DNS RESOLVER MONKEYPATCH
# ---------------------------------------------------------------------------
# Workaround for local network/ISP DNS blocking router.huggingface.co
def resolve_dns_udp(host: str, dns_servers: list[str] = ["8.8.8.8", "1.1.1.1"]) -> Optional[str]:
    # Standard DNS query for A record
    packet = b"\x12\x34\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00"
    qname = b""
    for part in host.split("."):
        qname += len(part).to_bytes(1, "big") + part.encode()
    qname += b"\x00"
    packet += qname + b"\x00\x01\x00\x01" # QTYPE=A, QCLASS=IN

    for dns_ip in dns_servers:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(2)
            s.sendto(packet, (dns_ip, 53))
            resp, _ = s.recvfrom(1024)
            s.close()
            ancount = int.from_bytes(resp[6:8], "big")
            if ancount == 0:
                continue
            idx = 12 + len(qname) + 4
            for _ in range(ancount):
                if resp[idx] & 0xc0 == 0xc0:
                    idx += 2
                else:
                    while resp[idx] != 0:
                        idx += resp[idx] + 1
                    idx += 1
                rtype = int.from_bytes(resp[idx:idx+2], "big")
                rdlength = int.from_bytes(resp[idx+8:idx+10], "big")
                rdata = resp[idx+10:idx+10+rdlength]
                idx += 10 + rdlength
                if rtype == 1 and rdlength == 4:
                    return ".".join(str(b) for b in rdata)
        except Exception:
            continue
    return None

# Resolve router.huggingface.co IP and patch urllib3 connection pool
HF_IP = resolve_dns_udp("router.huggingface.co")
org_create_connection = urllib3_cn.create_connection

def patched_create_connection(address, *args, **kwargs):
    host, port = address
    if host == "router.huggingface.co" and HF_IP:
        address = (HF_IP, port)
    return org_create_connection(address, *args, **kwargs)

urllib3_cn.create_connection = patched_create_connection

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
# 2. COIN TAG EXTRACTION
# ---------------------------------------------------------------------------
# Map of ticker -> list of keywords to match (ticker + common name variants)
COIN_KEYWORDS: dict[str, list[str]] = {
    "BTC":   ["btc", "bitcoin"],
    "ETH":   ["eth", "ethereum", "ether"],
    "SOL":   ["sol", "solana"],
    "XRP":   ["xrp", "ripple"],
    "ADA":   ["ada", "cardano"],
    "DOGE":  ["doge", "dogecoin"],
    "AVAX":  ["avax", "avalanche"],
    "LINK":  ["link", "chainlink"],
    "DOT":   ["dot", "polkadot"],
    "NEAR":  ["near", "near protocol"],
    "BNB":   ["bnb", "binance coin", "binance smart chain", "bsc"],
    "SUI":   ["sui"],
    "PEPE":  ["pepe"],
    "SHIB":  ["shib", "shiba", "shiba inu"],
    "LTC":   ["ltc", "litecoin"],
    "TRX":   ["trx", "tron"],
    "TON":   ["ton", "the open network", "toncoin"],
    "ATOM":  ["atom", "cosmos"],
    "MATIC": ["matic", "polygon"],
    "ARB":   ["arb", "arbitrum"],
    "OP":    ["optimism"],
    "UNI":   ["uni", "uniswap"],
    "AAVE":  ["aave"],
    "MKR":   ["mkr", "maker"],
    "CRV":   ["crv", "curve"],
    "LDO":   ["ldo", "lido"],
    "WIF":   ["wif", "dogwifhat"],
    "BONK":  ["bonk"],
    "INJ":   ["inj", "injective"],
    "SEI":   ["sei"],
    "APT":   ["apt", "aptos"],
    "FTM":   ["ftm", "fantom"],
    "ALGO":  ["algo", "algorand"],
    "HBAR":  ["hbar", "hedera"],
    "VET":   ["vet", "vechain"],
    "FIL":   ["fil", "filecoin"],
    "ICP":   ["icp", "internet computer"],
    "GRT":   ["grt", "the graph"],
    "SAND":  ["sand", "sandbox"],
    "MANA":  ["mana", "decentraland"],
    "AXS":   ["axs", "axie infinity"],
    "XLM":   ["xlm", "stellar", "stellar lumens"],
    "XMR":   ["xmr", "monero"],
    "BCH":   ["bch", "bitcoin cash"],
    "ETC":   ["etc", "ethereum classic"],
    "FLOKI": ["floki"],
    "WLD":   ["wld", "worldcoin"],
    "STX":   ["stx", "stacks"],
    "RUNE":  ["rune", "thorchain"],
    "DEFI":  ["defi", "decentralized finance"],
    "NFT":   ["nft", "nfts"],
}

# Words that should only match as whole words (avoid false positives)
WHOLE_WORD_ONLY = {"ton", "sei", "op", "uni", "grt", "fil", "sol", "link", "near"}


def extract_coin_tags(text: str) -> list[str]:
    """Return a deduplicated list of coin tickers found in *text*."""
    text_lower = text.lower()
    found = []
    for ticker, keywords in COIN_KEYWORDS.items():
        for kw in keywords:
            if kw in WHOLE_WORD_ONLY:
                pattern = r"\b" + re.escape(kw) + r"\b"
                if re.search(pattern, text_lower):
                    found.append(ticker)
                    break
            else:
                if kw in text_lower:
                    found.append(ticker)
                    break
    return list(dict.fromkeys(found))  # preserve insertion order, dedupe


# ---------------------------------------------------------------------------
# 3. RSS FETCHING
# ---------------------------------------------------------------------------
CUTOFF_HOURS = 24  # only keep articles published within this window


def parse_published(entry) -> Optional[datetime]:
    """Parse the published date from a feed entry, return UTC datetime or None."""
    ts = entry.get("published_parsed") or entry.get("updated_parsed")
    if ts:
        try:
            return datetime(*ts[:6], tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def fetch_all_feeds() -> list[dict]:
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
            summary_clean = re.sub(r"<[^>]+>", " ", summary)

            tags = extract_coin_tags(f"{title} {summary_clean}")

            articles.append({
                "title":     title,
                "url":       link,
                "source":    feed_meta["name"],
                "published": pub.isoformat() if pub else None,
                "coins":     tags,
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
        coins = set(article["coins"])
        matched = False

        for existing in primary:
            # Only fuzz-match within shared coin context (or both global)
            existing_coins = set(existing["coins"])
            shares_coin = bool(coins & existing_coins) or (not coins and not existing_coins)

            if shares_coin and titles_are_similar(title, existing["title"]):
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
                "coins":        article["coins"],
                "summary":      article.get("summary", ""),
                "sentiment":    None,
                "confidence":   None,
                "other_sources": [],
            })

    return primary


# ---------------------------------------------------------------------------
# 5. FINBERT SENTIMENT ANALYSIS  (Hugging Face Serverless Inference API)
# ---------------------------------------------------------------------------
# HF migrated to router.huggingface.co/hf-inference/models/
HF_MODEL_ID   = "ProsusAI/finbert"
HF_API_URL    = f"https://router.huggingface.co/hf-inference/models/{HF_MODEL_ID}"
HF_TOKEN      = os.environ.get("HF_TOKEN", "")

LABEL_MAP = {
    "positive": "Bullish",
    "negative": "Bearish",
    "neutral":  "Neutral",
}

MAX_TITLE_LEN  = 512   # char proxy for BERT token limit


def classify_sentiments(articles: list[dict]) -> list[dict]:
    """
    POST all article titles in a single batch payload to HF Serverless Inference API
    with a strict 5-second timeout. Falls back to Neutral=0.0 on any error, timeout,
    or model loading response.
    """
    if not articles:
        return articles

    if not HF_TOKEN:
        print("[WARN] HF_TOKEN not set — skipping sentiment, defaulting to Neutral.")
        for a in articles:
            a["sentiment"]  = "Neutral"
            a["confidence"] = 0.0
        return articles

    headers = {
        "Authorization": f"Bearer {HF_TOKEN}",
        "Content-Type":  "application/json",
    }

    titles  = [a["title"][:MAX_TITLE_LEN] for a in articles]
    payload = {
        "inputs":  titles,
        "options": {"wait_for_model": False},  # Do not hang if model is loading
    }

    try:
        print(f"Sending batch of {len(articles)} headlines to Hugging Face Inference API...")
        resp = requests.post(
            HF_API_URL,
            headers=headers,
            json=payload,
            timeout=5,  # strict 5-second timeout
        )
        
        if resp.status_code != 200:
            print(f"[WARN] HF API returned status code {resp.status_code}. Defaulting batch to Neutral.")
            for a in articles:
                a["sentiment"]  = "Neutral"
                a["confidence"] = 0.0
            return articles

        results = resp.json()
        
        if isinstance(results, dict) and "error" in results:
            print(f"[WARN] HF API returned error: {results['error']}. Defaulting batch to Neutral.")
            for a in articles:
                a["sentiment"]  = "Neutral"
                a["confidence"] = 0.0
            return articles

    except Exception as exc:
        print(f"[WARN] HF API connection error or timeout: {exc}. Defaulting batch to Neutral.")
        for a in articles:
            a["sentiment"]  = "Neutral"
            a["confidence"] = 0.0
        return articles

    # FinBERT returns results in different structures depending on the model/pipeline:
    # Format 1: [[{'label': 'pos', 'score': X}, {'label': 'neg', 'score': Y}, ...]] (batch top labels under results[0])
    # Format 2: [[{'label': 'pos', 'score': X}, ...], [{'label': 'neg', 'score': Y}, ...]] (list of lists, one per article)
    for idx, article in enumerate(articles):
        article["sentiment"]  = "Neutral"
        article["confidence"] = 0.0

        if not isinstance(results, list) or len(results) == 0:
            continue

        # Check Format 1: results is [[dict, dict, ...]] where length of results[0] matches articles
        if len(results) == 1 and isinstance(results[0], list) and len(results[0]) == len(articles):
            item = results[0][idx]
            if isinstance(item, dict):
                article["sentiment"]  = LABEL_MAP.get(item.get("label", "").lower(), "Neutral")
                article["confidence"] = round(item.get("score", 0.0), 4)

        # Check Format 2: results is a list of lists, one list of dicts per article
        elif idx < len(results) and isinstance(results[idx], list):
            label_scores = results[idx]
            if label_scores:
                best = max(label_scores, key=lambda x: x.get("score", 0.0) if isinstance(x, dict) else 0.0)
                article["sentiment"]  = LABEL_MAP.get(best.get("label", "").lower(), "Neutral")
                article["confidence"] = round(best.get("score", 0.0), 4)

    print("✓ Batch sentiment classification completed successfully.")
    return articles


# ---------------------------------------------------------------------------
# 6. MAIN
# ---------------------------------------------------------------------------
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "news.json")


def main():
    print(f"[{datetime.now().isoformat()}] Fetching RSS feeds…")
    raw = fetch_all_feeds()
    print(f"  → {len(raw)} raw articles fetched.")

    print("Deduplicating…")
    deduped = deduplicate(raw)
    print(f"  → {len(deduped)} unique stories after deduplication.")

    # Sort deduplicated stories newest first
    deduped.sort(key=lambda x: x["published"] or "", reverse=True)

    # Process sentiment for top 25 most recent headlines
    to_classify = deduped[:25]
    remaining = deduped[25:]

    if to_classify:
        print(f"Classifying sentiments for top {len(to_classify)} most recent headlines…")
        classified = classify_sentiments(to_classify)
    else:
        classified = []

    # For the remaining headlines, default to Neutral gracefully
    for a in remaining:
        a["sentiment"]  = "Neutral"
        a["confidence"] = 0.0

    final = classified + remaining

    # Final sort newest first
    final.sort(key=lambda x: x["published"] or "", reverse=True)

    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total":      len(final),
        "articles":   final,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # Also write to news.js for direct file:// protocol browsing without CORS issues
    JS_FILE = os.path.join(os.path.dirname(__file__), "news.js")
    with open(JS_FILE, "w", encoding="utf-8") as f:
        f.write(f"window.newsData = {json.dumps(output, ensure_ascii=False, indent=2)};")

    print(f"✓ Saved {len(final)} articles to {OUTPUT_FILE} and news.js")


if __name__ == "__main__":
    main()

