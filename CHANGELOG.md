# Changelog

All notable changes to CryptoFlash's `fetch_news.py` scraper are documented here.
Versions follow [Semantic Versioning](https://semver.org/) (`MAJOR.MINOR.PATCH`).
`news.json`'s existing field names and casing are a stability contract with
Wicktor's `Api.coinNews()` — breaking that contract is a MAJOR bump; new
additive fields are MINOR; bug fixes with no schema change are PATCH.

## [Unreleased]

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
