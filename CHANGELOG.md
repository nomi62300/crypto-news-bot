# Changelog

All notable changes to the Snitch project (formerly CryptoFlash) are documented
here — the `fetch_news.py`/`fetch_econ_calendar.py` backend scrapers and the
`index.html` frontend. Versions follow [Semantic Versioning](https://semver.org/)
(`MAJOR.MINOR.PATCH`). `news.json`'s existing field names and casing are a
stability contract with Wicktor's `Api.coinNews()` — breaking that contract is
a MAJOR bump; new additive fields/features are MINOR; bug fixes with no schema
change are PATCH.

## [Unreleased]

## [0.7.3] - 2026-08-15
### Added
- `stocks_snapshot` field in `fetch_news.py`: server-side Finnhub fetch for
  the Stocks & Indices Watchlist table (`STOCKS_WATCHLIST`, the same 17
  symbols the table already showed — 5 ETF index proxies, gold, and 11
  individual equities), daily-gated with the same "keep previous snapshot,
  mark `stale`" fallback pattern as `macro_snapshot`/`index_snapshot`/
  `commodity_snapshot`. Finnhub's `/quote` endpoint is single-symbol only
  (no batch), so each symbol is fetched individually and paced 1.1s apart
  to stay well under the free tier's 60 req/min cap. Wired into
  `scrape_news.yml`'s env block, reusing the already-set
  `FINNHUB_API_KEY` GitHub secret (previously used only by
  `fetch_econ_calendar.py`'s Finnhub fallback).

### Changed
- Migrated the Stocks & Indices Watchlist off its client-side Finnhub
  call. Previously the browser fetched each symbol directly via a
  client-embedded `FINNHUB_API_KEY` constant in `index.html`, which — on a
  static site with no backend — was necessarily visible in page source the
  moment a key was pasted in; the table was empty until that happened.
  That constant, `STOCK_WATCHLIST`, `fetchFinnhubQuote()`, and
  `fetchStocksQuotes()` are all removed. `renderStocksTable()`,
  `renderIndicesRow()`'s Finnhub-fallback branch, and the Forex tab's
  ticker tape (`buildTickerTapeForex()`) now all read the new
  `stocksSnapshotCache` (`data.stocks_snapshot`) instead — same pattern
  already used for `indexSnapshotCache`/`commoditySnapshotCache`. No key
  ever needs to touch `index.html` again. This was the last of the
  Watchlist-adjacent features still doing a direct browser-to-provider
  call; the Indices tile row got the equivalent fix earlier (0.6.x,
  `index_snapshot`).

## [0.7.2] - 2026-08-15
### Added
- TradingView's free, keyless Economic Calendar embed widget as a temporary
  stand-in for the Economic Calendar card, shown only when
  `econCalendarCache` has zero events (i.e. our own FMP/Finnhub sources are
  both plan-gated right now — confirmed in 0.7.1). Investigated
  alternatives first: ForexFactory scraping was ruled out (confirmed
  live — Cloudflare-protected, same "Just a moment..." managed challenge
  that already blocked Stooq; Scrapling's base package has no browser to
  get past it, and adding one was already ruled out early in this project
  for infra reasons). The custom day-grouped table (countdown timers,
  Weekly Calendar toggle, per-pair beat/miss effect notes) stays fully
  built and untouched — this is a dormant-feature swap: the moment
  `econ_calendar.json` has real events again, `renderEconCalendar()`
  renders the custom table instead of the widget automatically, no further
  code change needed.

## [0.7.1] - 2026-08-15
### Added
- Finnhub fallback for `fetch_econ_calendar.py`: FMP's `/stable/economic-
  calendar` returns `402 Payment Required` on the current plan (confirmed
  via the workflow's first-ever live run — it had never executed before,
  separate finding from the FMP plan-tier issue itself). Finnhub's
  `/calendar/economic` endpoint is confirmed reachable (a bad-key request
  returns `401`, not `404`, so the endpoint is real) and reuses the
  already-set `FINNHUB_API_KEY` GitHub secret — its exact free-tier access
  and field names (`time`/`prev`/etc., currency inferred from country via
  a new lookup table when absent) aren't verified against a live
  successful response yet, flagged for a follow-up check.

## [0.7.0] - 2026-08-14
### Added
- Line/area-chart sparklines (`renderLineSparkline()`) on the Indices/FX/
  Commodities big stat tiles, matching the Fincept reference look — kept
  distinct from the existing bar-chart `renderSparkline()`, which stays as
  the Gainers/Losers tables' trend-column style everywhere it's already
  used (Crypto Market, FX cross-pairs, Commodities).
  - FX tiles: `fetchForexRates()` switched from two point-fetches (latest +
    one 7-days-ago snapshot) to a single Frankfurter date-range call
    (`/v1/{7d-ago}..{today}`), which now also produces a real per-currency
    daily series (`fxCache.series`) feeding each pair's sparkline via the
    new `buildPairSeries()`, on top of still serving the existing
    latest/historical two-point comparison from the same response.
  - Indices/Commodities tiles: new `_twelvedata_time_series()` in
    `fetch_news.py`, one call per symbol (Twelve Data's `/time_series`
    doesn't batch like `/quote` does), attaching a `sparkline` array to
    each `index_snapshot`/Twelve-Data-sourced `commodity_snapshot` item.
    Paced 8s apart per symbol to stay under the free tier's 8 req/min cap
    (confirmed live in an earlier version: two quote batches back-to-back
    already 429's) — adds ~1.5-2 minutes to the one daily run that
    actually fetches, well within the job's 10-minute budget. Items
    sourced from API Ninjas (no historical endpoint on its free tier)
    simply have no `sparkline` field — tiles render fine without one.

### Changed
- Retail Positioning Extremes (myfxbook) card now shows only the 7 major
  USD pairs (`EURUSD`/`GBPUSD`/`USDJPY`/`USDCHF`/`AUDUSD`/`USDCAD`/
  `NZDUSD`) instead of every pair at ≥80% skew (~120+ pairs, mostly minor/
  cross pairs like `AUDCHF`/`NZDCAD` traders don't typically watch) —
  filtered client-side in `renderForexSentiment()`; the backend still
  fetches/stores the full set, only display is scoped.
- Removed the Indices row's "Top Gainers/Top Losers — Equities" tables
  (markup + the equities-derived block in `renderIndicesRow()`) — FX
  cross-pairs and Commodities keep theirs.

### Known limitations
- "Stocks & Indices Watchlist" and "Economic Calendar" cards were reported
  as empty by the user — neither is a bug: Finnhub needs its key pasted
  directly into `index.html`'s `FINNHUB_API_KEY` constant (client-side,
  not the `FINNHUB_API_KEY` GitHub secret, which this code path doesn't
  read at all), and the `Fetch Economic Calendar` workflow (daily cron,
  `FMP_API_KEY` already set correctly) simply hadn't run yet — confirmed
  via `gh run list` showing zero runs in its history since being merged.

## [0.6.3] - 2026-08-14
### Fixed
- VADER misclassified "Hyperliquid – HYPE holds near $57 as whale unloads
  1.95M tokens" as `Neutral` (confidence exactly `0.5`, i.e. a flat `0.0`
  compound score) — flagged live by the user. Root cause: the existing
  `FINANCE_LEXICON_OVERLAY` already covers `dump`/`dumped` as bearish but
  not `unload`/`unloads`, the word this specific article used — a real gap,
  not a one-off. Added `unload`/`offload`/`liquidated`/`liquidation`/
  `rug pull`/`depeg`/`insolvent` (bearish) and `accumulate`/`accumulation`
  (bullish) to the overlay. Verified live: the flagged article now scores
  `Bearish` at `0.625` confidence instead of the flat `Neutral` `0.5`.

## [0.6.2] - 2026-08-14
### Fixed
- X-sourced articles (`source_type: "x"`) vanished from `news.json`
  entirely whenever FxTwitter's cashtag-search endpoint failed for a
  single run — confirmed live: it intermittently 404s a whole batch
  (transient IP-based rate-limit/edge-block against the request's source,
  not a real "not found" — the identical query succeeds seconds later from
  elsewhere), and unlike `forex_sentiment`/`macro_snapshot` (which
  explicitly keep last-known-good data on failure), `raw`/`deduped`/`final`
  were entirely rebuilt from that run's own fetch each time with no grace
  period — two runs fetched 13 then 9 tweets, the next got 0 and every
  tweet disappeared instantly. Fixed with a one-retry-with-backoff per
  batch in `fetch_x_cashtags()`, plus a carry-forward step in `main()` that
  keeps previously-seen X-sourced articles still within the 48-hour cutoff
  when they're missing from the current run's output (a no-op when the
  fetch succeeds normally).

## [0.6.1] - 2026-08-14
### Fixed
- `forex_sentiment` (myfxbook) was completely non-functional at 0.6.0 time —
  every `get-community-outlook.json` call rejected the session as
  `"Invalid session."` even immediately after a successful login. Root
  cause, found via live diagnostics added directly to a production run:
  `login.json` returns the session token **already URL-encoded** (its
  base64 padding shows up literally as `%3D%3D` in the JSON body).
  `_myfxbook_login()` was passing that encoded string straight into
  `requests`' `params`, which encodes it *again* (`%3D` → `%253D`) — the
  server never saw a token it recognized. Fixed with a single `unquote()`
  call on the token right after login; confirmed live afterward — 120 pairs
  at ≥80% skew returned, correctly filtered and ranked. All of `forex_sentiment`'s
  field-name assumptions (`name`, `longPercentage`/`shortPercentage`,
  `longVolume`/`shortVolume`, `longPositions`/`shortPositions`) turned out
  correct on the first real attempt — no native popularity field, confirming
  the volume-derived ranking approach was the right call.

## [0.6.0] - 2026-08-14 (merged to `main` via PR #1)
### Added — Backend: forex sentiment, macro/commodity/index snapshots
- `forex_sentiment` — myfxbook community-outlook retail positioning,
  hourly-gated (reads its own previous `updated_at` back from `news.json`
  rather than an external cache), filtered to pairs at ≥80% long or short,
  popularity rank derived from relative volume. Shipped non-functional in
  this version (session token double-encoding bug) — see [0.6.1](#061---2026-08-14).
- `macro_snapshot` — Treasury 10Y yield, Fed funds rate, and market risk
  premium via FMP (primary), Alpha Vantage (fallback), daily-gated.
  Confirmed live. `cpi_yoy`/`gdp_real`/`unemployment_rate`/`nonfarm_payroll`
  are still `null` pending live verification of FMP's economic-indicators
  field names for those specific series.
- `commodity_snapshot` — went through several providers before landing on a
  working combination, each ruled out for a concrete, live-tested reason:
  Stooq (blocked by a Cloudflare bot-challenge on every request, browser and
  server-side alike), FMP's plain commodity symbols and its forex-style
  XAUUSD/XAGUSD symbols (both return `402 Payment Required` on the current
  plan), Alpha Vantage (works for WTI/Brent/Natural Gas/Copper via its
  time-series endpoints, but has no working gold/silver source — its
  `CURRENCY_EXCHANGE_RATE` doesn't actually support `XAU`/`XAG` despite that
  being a commonly-cited trick), Twelve Data (its free tier turned out to
  only cover equities/ETFs, not raw commodity instruments — confirmed via
  its own `/symbol_search`, so it's used with ETF proxies: `USO`, `BNO`,
  `GLD`, `SLV`, `UNG`, `CPER`). API Ninjas was added last as the real-price
  primary source, but its free tier only covers a *rotating weekly subset*
  of commodities — the final design merges all four providers **per
  commodity symbol**, not all-or-nothing per provider (a real bug caught
  during testing: a partial API Ninjas success, only Gold available that
  week, was short-circuiting the whole fetch and silently discarding the
  other 5 commodities Twelve Data could have supplied).
- `index_snapshot` — new field, S&P 500/Nasdaq 100/Dow/Russell 2000/
  Volatility via Twelve Data ETF proxies (`SPY`/`QQQ`/`DIA`/`IWM`/`VIXY`),
  daily-gated. Moves the Indices tile row's data server-side instead of
  requiring a client-embedded `FINNHUB_API_KEY` (which the equities Top
  Gainers/Losers table under that row still needs separately).

### Added — Frontend: economic calendar redesign, market data rows
- Economic calendar rebuilt into a day-grouped view (mirrors the Dashboard's
  `groupArticlesByDate()` idiom): compact mode shows only the next 2
  non-empty upcoming days, a "Weekly Calendar" toggle inline-expands to the
  full week with past days visibly faded (impact pills desaturated too) and
  a live-ticking `HH:MM:SS` countdown per event (`00:00:00` for past ones).
  The existing HIGH/MEDIUM beat/miss effect-rule logic is unchanged, now
  additionally translated into per-major-pair direction (e.g. a USD event
  shows implied EURUSD/USDJPY/etc. direction, not just an abstract
  currency-level note).
- Forex Market tab: Indices/FX/Commodities stat-tile rows (6 tiles each,
  bar-chart sparklines) with Top Gainers/Top Losers tables underneath,
  stacked as three always-visible rows — plus the myfxbook and macro-
  snapshot panels.
- Crypto Market tab: replaced the ALL/GAINERS/LOSERS/MOST ACTIVE toggle
  with side-by-side Top Gainers/Top Losers tables; the full market-cap-
  sorted table stays below, unchanged.
- Dashboard: independent "Tweets Only" filter toggle (not part of the
  category strip, since it's a different, combinable axis) plus a distinct
  tweet card treatment (`@handle`, likes/reposts/replies, follower count)
  so X-sourced articles no longer render identically to RSS ones.
- Visual pass: reverted to full monospace typography (an Inter-based
  redesign was tried mid-session, then explicitly reverted back to
  Fincept-style monospace per direction), bar-chart sparklines replacing
  the previous line sparklines, squarer card corners (14px/8px radius down
  to 4px/3px), category filter bar hidden on the market tabs, tab labels
  shortened ("Cr. Mkt"/"FX Mkt").

### Fixed
- `fetch_scrapling_sources()` crashed the *entire* scrape run with
  `AttributeError: 'Selector' object has no attribute 'strip'` — caught by
  the first live workflow run after this session's other changes landed
  (a pre-existing bug, unrelated to any of the new features, that just
  hadn't been triggered before). Scrapling's `.css()` with a `::text`/
  `::attr()` selector doesn't reliably return plain strings across match
  shapes; fixed with defensive text extraction plus scoping the per-source
  `try`/`except` around the whole parse loop so one broken site selector
  can't take the whole run down.

### Ops
- New GitHub secrets: `MYFXBOOK_EMAIL`, `MYFXBOOK_PASSWORD`, `FMP_API_KEY`,
  `ALPHA_VANTAGE_API_KEY`, `TWELVE_DATA_API_KEY`, `API_NINJAS_KEY`.
- **Merged `snitch-backend` → `main` via PR #1** — this version and the
  three prior `snitch-backend`-only versions (0.3.0–0.5.0) are now live in
  production (GitHub Pages, Wicktor's feed). `news.json`/`news.js`/
  `token_usage.json` had diverged during the merge since `main` had its own
  independent 15-minute scheduled cron running the whole time — resolved by
  taking `snitch-backend`'s versions, since these are pure generated output
  regenerated on every run, not hand-maintained source.

### Known limitations
- `forex_sentiment` (myfxbook) did not populate at this version's initial
  release — see [0.6.1](#061---2026-08-14) for the root cause and fix
  (a session-token double-encoding bug, not an account issue as first
  suspected).
- Indices/Commodities coverage via Twelve Data and API Ninjas' free tiers is
  ETF-proxy-based (Twelve Data) or a rotating weekly subset (API Ninjas),
  not true composite-index or always-guaranteed spot data — a documented
  tradeoff of the free tiers involved, not a bug.
- A commodity's `changes_percentage` is `null` the first day it's sourced
  from a new provider (API Ninjas has no % change field of its own; it's
  computed from yesterday's stored price for the same symbol, so there's
  nothing to diff against on day one).

## [0.5.0] - 2026-08-14 (branch: snitch-backend, not yet merged to main)
### Added — Backend: non-RSS scraping, geopolitical events, X/Twitter cashtag search
Evaluated 16 external repos surfaced by the user as candidates to improve
`fetch_news.py`'s data gathering. Most were ruled out — several need
persistent server infrastructure Snitch's GitHub-Actions-cron architecture
deliberately avoids (HeadlessX, wigolo, OpenStock, MiroFish), some are
AGPLv3-licensed (a real constraint on direct code reuse), one is
non-automatable (ai-berkshire's scraper needs interactive login), and three
X/Twitter alternatives (`twscrape`, `twitter-web-exporter`, `tweetclaw`) were
evaluated and rejected (real-account credential/suspension risk,
browser-only/non-automatable, and paid-vendor dependency respectively). Three
things survived, all free/keyless/no-persistent-server:
- **Scrapling** (`fetch_scrapling_sources()`) — adaptive HTML parsing (base
  package only, no browser) for two confirmed non-RSS sources:
  **InvestingLive** (formerly ForexLive — the domain now redirects entirely;
  server-renders real headlines, no RSS available) and **Watcher.Guru**
  (crypto/stocks news, `/feed` blocked by Cloudflare). Selectors use
  attribute-*contains* matching rather than exact CSS-module hash names
  where the site's build system generates per-deploy hashes, so they survive
  redeploys better than an exact-class-name selector would. (Wu Blockchain,
  originally considered, was dropped — its real domain already publishes a
  working Atom feed in Chinese; the "English" domain some sources pointed to
  is an unrelated parked/for-sale placeholder, not a live site.)
- **Geopolitical/disaster events** (`fetch_geopolitical_events()`) — new
  4th `asset_class` value `"geopolitics"`, feeding the `GEOPOLITICS`
  category (previously only arose incidentally from RSS text matching, never
  had a dedicated source). **GDELT** DOC 2.0 API (article `tone` mapped
  deterministically to sentiment — no Groq/FinBERT call, neither is trained
  for structured event records) and **USGS** earthquake GeoJSON feed
  (magnitude-based mapping), both free/keyless. New fields: `event_source`
  (`"gdelt"|"usgs"`), `magnitude` (USGS only), `sentiment_engine` values
  `"gdelt_tone"`/`"usgs_magnitude"`.
- **X/Twitter cashtag search** (`fetch_x_cashtags()`) — searches FxTwitter's
  public mirror (`api.fxtwitter.com/2/search`, no login, no official paid
  API) for tweets containing `$TICKER` cashtags for a fixed list of major
  coins, rather than a fixed account watchlist — directly matches the need
  (tweeter's name + full tweet text, filtered to actual cashtag mentions).
  New `source_type: "x"` value (extends the previously-dormant field —
  `"rss"` was the only real value before this; a Reddit integration was
  scoped then shelved in Phase 2 for unrelated reasons). New fields `likes`,
  `reposts`, `replies`.

### Fixed
- `deduplicate()` previously hard-coded `sentiment`/`confidence`/
  `sentiment_engine` to `None` on every new story record, which would have
  silently discarded GDELT/USGS's pre-computed deterministic sentiment the
  moment it passed through dedup — now preserves any pre-set values from the
  source article instead of always overwriting them.

### Known limitations / real risks found during implementation, not just documented
- **GDELT rate-limiting**: hit persistent `HTTP 429`s during development
  testing that outlasted their documented "one request per 5 seconds" policy
  by several minutes, and timed out entirely during full-pipeline testing —
  `_fetch_gdelt_events()` is wrapped fail-soft (catches, logs, returns `[]`)
  and should be treated as best-effort, not a reliable source. USGS had no
  such issues.
- **X cashtag search signal-to-noise**: unrestricted cashtag search surfaced
  mostly low-quality content in testing (presale/shill accounts, bot-style
  "top gainers" spam, airdrop-phishing patterns, non-English chatter) —
  152 raw results narrowed to 16 after adding a follower-count gate
  (`X_MIN_FOLLOWERS = 10,000`, found to be a far more reliable quality
  signal than like/repost counts, which stayed near-zero across nearly all
  results regardless of legitimacy) plus expanded spam-keyword and
  non-Latin-script filtering, and restricting the cashtag list to 20
  well-established tickers (`X_MAJOR_TICKERS`) rather than the full ~500-coin
  registry. This is real, live-tuned filtering, not a theoretical design —
  still expect some residual noise; crypto-Twitter is inherently noisy.
- Scrapling's "self-healing" auto-match needs persisted storage across runs
  to provide real cross-run value — not configured this phase (selectors are
  plain CSS selectors that will need manual updates if either site
  redesigns; see code comments in the Scrapling section).
- ACLED (armed-conflict event data) was considered for the geopolitical
  events source but not implemented — its free-tier registration terms need
  a separate feasibility check first.

## [0.4.0] - 2026-08-13 (branch: snitch-backend, not yet merged to main)
### Added — Frontend rebuild (Phase 3)
- Full rebrand: CryptoFlash → **Snitch**, new wordmark logo (JetBrains Mono,
  `#f5cc01` accent), new `favicon.svg` + PNG fallbacks, updated title/meta
  description.
- Site-wide Fincept Terminal-inspired dark theme: near-black background,
  off-white/muted-gray text, monospace throughout (dropped Inter), `#f5cc01`
  accent replacing the previous gold, sentiment colors (green/red/gray for
  Bullish/Bearish/Neutral) kept visually distinct from the accent.
- Simplified navigation to 3 tabs: **Dashboard** (all-asset-class news feed +
  overview stats + category filter strip), **Crypto Market**, and
  **Forex/Stocks Market** — replaced the old 2-tab Terminal/Dashboard layout
  and an earlier 5-tab iteration; per-asset-class news browsing now happens
  via the category filter strip on Dashboard rather than separate tabs.
- New category filter strip (ALL/CRYPTO/FOREX/STOCKS/ECONOMIC/REGULATORY,
  driven by the `category` field) alongside the existing ticker-chip filter.
- New per-article detail panel (slide-over on desktop, full-screen overlay on
  mobile/tablet) opening on row click, with OPEN (external link), COPY URL,
  and SAVE (bookmark, `localStorage`-persisted) actions — replaces the old
  direct-external-link row behavior.
- `source_flag` warning icon, `sentiment_engine` hover tooltip, and a dormant
  (untestable — no live Reddit data) `source_type`/`upvotes`/`num_comments`
  row-rendering branch, all additive to the existing row template.
- **Crypto Market tab**: CoinGecko-powered (free, keyless) global stats strip
  (market cap, 24h volume, BTC dominance, Fear & Greed) and a 100-coin table
  (price/24h%/market cap/volume/7D sparkline) with client-side-only
  ALL/GAINERS/LOSERS/MOST ACTIVE re-sorting (one cached fetch, no extra API
  calls per toggle). Crypto ticker tape (previously global) now lives here.
- **Forex/Stocks Market tab**: Frankfurter-powered (free, keyless) FX
  cross-pair Top Gainers/Losers with pips, a Relative Currency Strength
  chart, an approximate USD-index card (weighted geometric mean vs. majors,
  explicitly labeled "not the official ICE DXY"), a Finnhub-powered
  stocks/ETF-index watchlist (gracefully skips itself if no
  `FINNHUB_API_KEY` is configured — client-embedded key is an inherent
  tradeoff of a static/no-backend site, documented in code), and an economic
  calendar reader for `econ_calendar.json` (honest empty state, not an error,
  when the file doesn't exist yet). Forex ticker tape lives here.
- New backend script `fetch_econ_calendar.py` + new GitHub Actions workflow
  `fetch_econ_calendar.yml` (daily cron, separate from the 15-minute news
  scrape) — calls Financial Modeling Prep's free-tier economic-calendar
  endpoint, fails soft (preserves last-good data) on missing key/quota/error.
  Needs a user-provided `FMP_API_KEY` GitHub secret to actually populate data
  (same self-managed-secret pattern as `GROQ_API_KEY`).
- `.gitignore` added (excludes the `fincept design/` visual-reference
  screenshots from version control — session reference material, not a
  deliverable).

### Fixed
- FX pip-size calculation used `pair.includes('JPY')` (matched JPY appearing
  *anywhere* in a cross-pair, e.g. `JPY/CAD`) instead of checking whether JPY
  is specifically the *quote* currency — caused several JPY-as-base cross
  pairs to display "0.0 pips" despite a real, non-zero % change. Now checks
  `pair.split('/')[1] === 'JPY'`.

### Known limitations
- No free API exists for central bank policy rates, sovereign bond yields, or
  CDS risk (confirmed via research) — not included on the Forex/Stocks Market
  page. Myfxbook-style crowd long/short positioning also excluded (its API
  requires a login-derived session unsafe to embed client-side, and neither
  its public-page accessibility nor its Terms of Service could be confirmed
  permit scraping) — Relative Currency Strength (real, computed data) is the
  built alternative.
- Economic calendar requires a user-supplied `FMP_API_KEY`; without one the
  Forex/Stocks Market page shows an honest empty state rather than data.
- Stocks/ETF watchlist requires a user-supplied `FINNHUB_API_KEY`, embedded
  client-side (visible in page source) since this is a static site with no
  backend to hide it behind — same tradeoff already accepted for other
  client-side-only integrations on this page.
- This version lives on the `snitch-backend` branch only; `main` still runs
  the pre-Phase-3 frontend and `v0.2.0` backend until this branch is
  explicitly merged.

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
