#!/usr/bin/env python3
from __future__ import annotations
"""
fetch_econ_calendar.py
-----------------------
Fetches upcoming/recent economic calendar events (Fed/ECB/BoE releases, GDP,
CPI, employment data, etc.) from Financial Modeling Prep's economic-calendar
endpoint and writes the result to econ_calendar.json.

Separate from fetch_news.py by design: different data domain (scheduled
macro events, not news articles), different refresh cadence (daily is
plenty — these events don't change intraday), and a different upstream API.
Runs on its own GitHub Actions schedule (see .github/workflows/
fetch_econ_calendar.yml), not the 15-minute news cron.
"""

import json
import os
from datetime import datetime, timezone, timedelta

import requests

FMP_BASE = "https://financialmodelingprep.com/stable/economic-calendar"
FINNHUB_BASE = "https://finnhub.io/api/v1/calendar/economic"

# Currency inferred from country when Finnhub's response doesn't include one
# directly (confirm live once verified) — covers the majors this project
# already cares about elsewhere (FX_MAJORS in index.html).
COUNTRY_TO_CURRENCY = {
    "US": "USD", "EU": "EUR", "EA": "EUR", "GB": "GBP", "JP": "JPY",
    "CH": "CHF", "AU": "AUD", "CA": "CAD", "NZ": "NZD", "CN": "CNY",
    "DE": "EUR", "FR": "EUR", "IT": "EUR", "ES": "EUR",
}

# Window fetched: a few days back (so "yesterday"-style views have data)
# through two weeks ahead (covers "this week"/"next week" views). Well
# within FMP's documented ~90-day max range per request.
DAYS_BACK = 3
DAYS_FORWARD = 14

OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "econ_calendar.json")

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


def normalize_impact(raw: str) -> str:
    """FMP's impact casing isn't guaranteed — normalize to HIGH/MEDIUM/LOW,
    defaulting unrecognized values to LOW rather than dropping the event."""
    val = (raw or "").strip().upper()
    if val in ("HIGH", "MEDIUM", "LOW"):
        return val
    return "LOW"


def _fetch_events_fmp() -> list[dict]:
    api_key = os.environ.get("FMP_API_KEY", "")
    if not api_key:
        return []

    today = datetime.now(timezone.utc).date()
    date_from = (today - timedelta(days=DAYS_BACK)).isoformat()
    date_to = (today + timedelta(days=DAYS_FORWARD)).isoformat()

    params = {"from": date_from, "to": date_to, "apikey": api_key}

    try:
        resp = requests.get(FMP_BASE, params=params, headers=DEFAULT_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        print(f"[WARN] FMP economic-calendar request failed: {exc}")
        return []

    if not isinstance(data, list):
        # FMP returns an error object (e.g. {"Error Message": "..."}) on
        # plan/auth failures rather than raising an HTTP error status.
        print(f"[WARN] Unexpected FMP response shape (likely a plan/auth error): {str(data)[:300]}")
        return []

    events = []
    for item in data:
        try:
            events.append({
                "date":     item.get("date"),
                "country":  item.get("country"),
                "event":    item.get("event"),
                "currency": item.get("currency"),
                "actual":   item.get("actual"),
                "estimate": item.get("estimate"),
                "previous": item.get("previous"),
                "impact":   normalize_impact(item.get("impact")),
            })
        except Exception:
            continue  # skip malformed individual entries, don't fail the whole run

    return events


def _fetch_events_finnhub() -> list[dict]:
    """Fallback only, used when FMP's economic-calendar call fails (confirmed
    live: 402 Payment Required on the current FMP plan). Finnhub's endpoint
    is reachable (confirmed: a bad-key request returns 401, not 404, so the
    endpoint itself is real) but its exact free-tier availability and field
    names haven't been verified against a live successful response yet —
    read defensively, flagged for a follow-up check once FINNHUB_API_KEY's
    actual access level is confirmed."""
    api_key = os.environ.get("FINNHUB_API_KEY", "")
    if not api_key:
        return []

    today = datetime.now(timezone.utc).date()
    date_from = (today - timedelta(days=DAYS_BACK)).isoformat()
    date_to = (today + timedelta(days=DAYS_FORWARD)).isoformat()

    try:
        resp = requests.get(
            FINNHUB_BASE,
            params={"from": date_from, "to": date_to, "token": api_key},
            headers=DEFAULT_HEADERS, timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        print(f"[WARN] Finnhub economic-calendar request failed: {exc}")
        return []

    raw_events = data.get("economicCalendar") if isinstance(data, dict) else None
    if not isinstance(raw_events, list):
        print(f"[WARN] Unexpected Finnhub response shape: {str(data)[:300]}")
        return []

    events = []
    for item in raw_events:
        try:
            # Finnhub's "time" is a full "YYYY-MM-DD HH:MM:SS" timestamp;
            # keep just the date portion to match FMP's "date" field shape.
            raw_time = item.get("time") or ""
            date_str = raw_time.split(" ")[0] if raw_time else None
            country = item.get("country")
            currency = item.get("currency") or COUNTRY_TO_CURRENCY.get((country or "").upper())
            events.append({
                "date":     date_str,
                "country":  country,
                "event":    item.get("event"),
                "currency": currency,
                "actual":   item.get("actual"),
                "estimate": item.get("estimate"),
                "previous": item.get("prev"),
                "impact":   normalize_impact(item.get("impact")),
            })
        except Exception:
            continue

    return events


def fetch_events() -> list[dict]:
    """FMP primary, Finnhub fallback (only called when FMP returns nothing)."""
    events = _fetch_events_fmp()
    source = "fmp"
    if not events:
        events = _fetch_events_finnhub()
        source = "finnhub"

    if events:
        print(f"  [INFO] econ_calendar: using {source}")
        events.sort(key=lambda e: e.get("date") or "")
    return events


def main():
    print(f"[{datetime.now().isoformat()}] Fetching economic calendar…")
    events = fetch_events()
    print(f"  → {len(events)} events fetched.")

    # Fail-soft: if the fetch failed/returned nothing, keep whatever was
    # previously written rather than overwriting good data with an empty
    # file (mirrors fetch_news.py's existing-data preservation pattern).
    if not events and os.path.exists(OUTPUT_FILE):
        print("  [WARN] No events fetched — leaving existing econ_calendar.json unchanged.")
        return

    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(events),
        "events": events,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"✓ Saved {len(events)} events to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
