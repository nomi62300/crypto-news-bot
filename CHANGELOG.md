# Changelog

All notable changes to CryptoFlash's `fetch_news.py` scraper are documented here.
Versions follow [Semantic Versioning](https://semver.org/) (`MAJOR.MINOR.PATCH`).
`news.json`'s existing field names and casing are a stability contract with
Wicktor's `Api.coinNews()` — breaking that contract is a MAJOR bump; new
additive fields are MINOR; bug fixes with no schema change are PATCH.

## [Unreleased]

## [0.3.0] - 2026-08-13 (branch: snitch-backend, not yet merged to main)
### Added
- `asset_class` field (`"crypto"` | `"forex"` | `"stocks"`) — lowercase,
  additive, distinct from the existing uppercase `category` field (which
  stays more granular: MARKETS/ECONOMIC/REGULATORY/etc.). Derived directly
  from each feed's coarse RSS_FEEDS category, no extra classification cost.
- `currency_pairs` field — populated only for `asset_class == "forex"` with
  constituent currency codes found in the article (not full pairs; `tickers`
  stays populated for crypto/stocks as before). Backed by a new static
  `FOREX_CURRENCIES` registry (9 major currencies) and `extract_currency_codes()`.
- `STOCK_TICKERS` registry, seeded with the 11 tickers currently live on
  Bybit's tokenized-stock ("xStocks") universe (AAPL, AMZN, COIN, CRCL,
  GOOGL, HOOD, MCD, META, NVDA, SPCX, TSLA) — confirmed via Bybit's
  instruments-info API (`symbolType: "xstocks"`) rather than assumed, so tag
  coverage matches what the downstream Wicktor frontend can actually display.
- **FinBERT (`ProsusAI/finbert`) as the forex/stocks primary sentiment
  engine**, replacing v0.2.0's tier-based routing for forex/stocks
  specifically: `asset_class in ("forex", "stocks")` now always routes to
  FinBERT regardless of source tier (ending Groq calls for tier-1 forex/stock
  sources like Fed/ECB/SEC/MarketWatch — that Groq budget now goes entirely
  to crypto), falling back to the existing VADER/keyword chain
  (`classify_fallback()`) on FinBERT unavailability or a per-article error.
  Crypto's tier-based Groq/VADER routing (`classify_crypto()`) is
  byte-for-byte unchanged. New `sentiment_engine: "finbert"` value.
- `finbert_training_log.jsonl` — append-only log of every FinBERT
  classification (headline, summary, label, score, timestamp), committed by
  GitHub Actions alongside `news.json`/`news.js`/`token_usage.json`. Exists
  to enable a **separate, future** task: calibrating VADER's finance lexicon
  against FinBERT's own historical judgments, with the eventual goal of
  retiring the `torch`/`transformers` dependency once VADER's accuracy is
  proven close enough. That calibration script is *not* built in this phase —
  this only accumulates the data it would need.
- `actions/cache` step in the GitHub Actions workflow, keyed on
  `hf-model-finbert-ProsusAI-v1`, caching `~/.cache/huggingface` so the
  ~438MB FinBERT model isn't re-downloaded every 15-minute run.

### Fixed
- STOCKS-category articles previously never got any `tickers` populated,
  because ticker extraction always searched the crypto coin registry
  regardless of feed category. `fetch_all_feeds()` now routes extraction by
  feed category: CRYPTO → crypto registry (unchanged), STOCKS → the new
  `STOCK_TICKERS` registry, FOREX → no tickers (uses `currency_pairs` instead).

### Ops
- `requirements.txt`: added `torch`, `transformers`, `numpy<2` (the pin
  avoids a real NumPy 2.x/torch ABI incompatibility — `numpy>=2` breaks
  `torch`'s compiled extensions, manifesting as `RuntimeError: Numpy is not
  available` at inference time, not at install time).
- Workflow: `finbert_training_log.jsonl` added to the existing guarded
  commit step (same pattern as `token_usage.json`).

### Known limitations
- FinBERT reads company/asset tone well (its actual training distribution —
  earnings beats/misses, recalls, etc.) but doesn't do macro-economic
  directional reasoning: in testing it classified "ECB cuts interest rates
  amid slowing inflation" as negative, when rate cuts are often bullish for
  risk assets depending on framing. VADER has the same blind spot, so this
  is a shared limitation across both non-Groq engines, not specific to
  choosing FinBERT over VADER for forex/stocks.
- This version lives on the `snitch-backend` branch only. `main` (and the
  live GitHub Actions schedule / Wicktor's production feed) still runs
  `v0.2.0` until this branch is explicitly merged.

## [0.2.0] - 2026-08-13
### Added
- `category` field on articles (`CRYPTO`, `FOREX`, `STOCKS`, `MARKETS`, `ECONOMIC`,
  `REGULATORY`, `GEOPOLITICS`) — lets downstream consumers filter macro/forex/stock
  news that has no ticker to match against.
- `region` field on articles (`US`, `EU`, `ASIA`, `INDIA`, `MENA`, `GLOBAL`).
- `source_flag` field (`"state_media"`, `"caution"`, or `null`) via a new
  `SOURCE_FLAGS` lookup table, checked against `source`. Surfaced only — not
  filtered on.
- `sentiment_engine` field (`"groq"` | `"vader"` | `"keyword"`) recording which
  engine actually classified each article.
- Forex/macro and stocks/regulatory RSS coverage: Federal Reserve, ECB Press,
  Bank of England, FXStreet, SEC Press Releases, MarketWatch, Seeking Alpha
  (all verified live before adding). Each feed now carries a `category` and a
  `tier` (1-4) used for sentiment-engine routing.
- Tiered sentiment engine chain: Groq (`llama-3.1-8b-instant`) is primary for
  tier-1/2 sources (wire services, central banks, major financial media);
  VADER (`vaderSentiment`, with a finance-tuned lexicon overlay) is primary by
  design for tier-3/4 sources (blogs/aggregators) and the automatic fallback
  for tier-1/2 when Groq is rate-limited, over budget, or errors; a
  dependency-free keyword scorer is the final fallback if VADER itself isn't
  installed.
- Groq classification prompt extended to return `category` and `region`
  alongside `sentiment`/`tickers` in the same call — no added API cost.
- Token-budget guard: daily Groq token usage is persisted to
  `token_usage.json` (committed alongside `news.json`/`news.js` by the GitHub
  Actions workflow so it survives across scheduled runs) and routing to Groq
  stops once usage crosses 75% of the 500K TPD ceiling for the day, falling
  back to VADER instead of risking a hard 429 mid-run.
- Retry/backoff on Groq 429s: one short-delay retry per batch, then that
  batch falls to VADER rather than blocking the whole scrape run.
- Per-run token usage logging to stdout (visible in GitHub Actions logs) as
  the leading indicator for whether the tiered-routing split needs tuning.

### Changed
- `clean_tickers()` now splits comma-joined ticker strings (e.g. Groq
  occasionally returning `"ADA,XRP"` as one array element) into separate
  tickers before cleaning.
- `NOISE_WORDS` expanded with `US`, `DATA`, `BILL`, `CASH`, `OPEN`, `BEAT`,
  `GDP`, `IPO`, `CPI`, `PMI` — confirmed via a scan of live `news.json` that
  `US`, `DATA`, `CASH`, and `OPEN` were slipping through as false-positive
  tickers (19, 29, 18, and 8 occurrences respectively).
- The Python crypto-keyword prefilter (`matches_crypto_prefilter`) now only
  applies to `CRYPTO`-category feeds. Forex/macro/stock headlines frequently
  have zero overlap with crypto keywords (e.g. "Fed holds rates steady") and
  would have been silently dropped otherwise.
- Sentiment/relevance routing only runs on genuinely new stories; articles
  the dedup step recognizes as republished/updated versions of an
  already-scored story reuse their prior `sentiment`, `confidence`,
  `category`, `region`, and `sentiment_engine` instead of re-spending tokens.
- `is_crypto_relevant`'s meaning broadened (field name/values unchanged) from
  strictly "relevant to crypto" to "relevant to its assigned asset-class
  category" now that the pipeline also covers forex/stocks — Wicktor's crypto
  consumption is unaffected since it only ever received crypto articles.

### Fixed
- Historical ticker-extraction bug where noise words leaked into the
  `tickers` array on live data (see NOISE_WORDS expansion above).

### Ops
- `requirements.txt`: added `vaderSentiment`.
- GitHub Actions workflow now also commits `token_usage.json` when present,
  so the token-budget guard's daily counter persists across the 15-minute
  cron runs (each run starts from a fresh checkout). Schedule and trigger
  conditions unchanged.

### Known limitations
- A handful of pre-existing RSS feeds are currently failing independent of
  this change (The Block: 403, FXStreet Crypto: 404, Bankless: SSL hostname
  mismatch, DL News: 404, CoinQuora: timeout, CryptoMode: 403) — not touched
  in this upgrade since they were already broken before it.
- MarketWatch's "top stories" feed is general news, not stock-specific,
  so off-topic articles (personal finance columns, human-interest pieces)
  can pass through when Groq is unavailable and articles fall to the VADER/
  keyword engines, since only Groq performs asset-class relevance filtering.
  Expected to self-correct once Groq is reachable given MarketWatch is tier 2.

## [0.1.0] - 2026-08-09
Baseline version at the start of changelog tracking — reflects the scraper as
verified live in production before this upgrade.
### Included
- 30+ crypto-only RSS sources, fuzzy title deduplication, Groq
  (`llama-3.1-8b-instant`) sentiment classification with a Neutral/0.50
  fallback on any error or missing API key.
- Dynamic CoinGecko-backed ticker registry (top 500 coins) with a static
  `FALLBACK_COINS` dict as a safety net.
- `news.json` schema: `updated_at`, `total`, `articles[]` with `title`, `url`,
  `source`, `published`, `tickers`, `summary`, `sentiment`, `confidence`,
  `other_sources`, `is_crypto_relevant`.
- 48-hour article retention window; incremental re-use of already-classified
  articles across runs by URL/title match.
