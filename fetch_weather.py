#!/usr/bin/env python3
"""
Fetches a 7-day ETo / rainfall forecast for each Ag Logic potato region from
Open-Meteo (free, no API key needed) and writes data.json.

This is run automatically by .github/workflows/update-weather.yml on a daily
schedule. You can also run it yourself locally with: python3 fetch_weather.py

Reliability notes:
- Each region is retried a few times (with a growing pause) if Open-Meteo
  errors out or rate-limits us.
- There is a short pause between regions so we don't hit the rate limit.
- If a region still fails after all retries, we keep that region's previous
  forecast from the existing data.json rather than writing null. (A null
  region breaks the Power Automate email flow.)
"""
import json
import os
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

# Real-world coordinates for each region shown on the calculator's map.
REGIONS = [
    {"id": "smithton",       "name": "Smithton",              "lat": -40.8417, "lon": 145.1250},
    {"id": "table-cape",     "name": "Table Cape / Wynyard",   "lat": -40.9839, "lon": 145.7178},
    {"id": "sassafras",      "name": "Sassafras / Devonport",  "lat": -41.2818, "lon": 146.4857},
    {"id": "waterhouse",     "name": "Waterhouse",             "lat": -40.9574, "lon": 147.5791},
    {"id": "scottsdale",     "name": "Scottsdale",             "lat": -41.1611, "lon": 147.5164},
    {"id": "cressy",         "name": "Cressy",                 "lat": -41.6830, "lon": 147.0830},
    {"id": "campbell-town",  "name": "Campbell Town",          "lat": -41.9167, "lon": 147.5000},
    {"id": "bothwell",       "name": "Bothwell",               "lat": -42.3833, "lon": 147.0000},
    {"id": "marion-bay",     "name": "Marion Bay",             "lat": -42.7970, "lon": 147.9230},
]

API_URL = "https://api.open-meteo.com/v1/forecast"
MAX_ATTEMPTS = 4          # tries per region
PAUSE_BETWEEN_REGIONS = 1.5  # seconds


def fetch_region_week(lat, lon):
    """Calls Open-Meteo for one location and returns a 7-day list of
    {date, eto, rain} — the exact shape the calculator expects."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "et0_fao_evapotranspiration,precipitation_sum",
        "timezone": "Australia/Hobart",
        "forecast_days": 7,
    }
    url = API_URL + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as resp:
        payload = json.load(resp)

    daily = payload["daily"]
    dates = daily["time"]
    eto_vals = daily["et0_fao_evapotranspiration"]
    rain_vals = daily["precipitation_sum"]

    week = []
    for i in range(len(dates)):
        week.append({
            "date": dates[i],
            "eto": round(eto_vals[i], 2) if eto_vals[i] is not None else None,
            "rain": round(rain_vals[i], 2) if rain_vals[i] is not None else None,
        })
    # Treat a week with any missing value as a failure so it gets retried.
    if len(week) < 7 or any(d["eto"] is None or d["rain"] is None for d in week):
        raise ValueError("Open-Meteo returned incomplete data")
    return week


def fetch_with_retries(region):
    last_exc = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return fetch_region_week(region["lat"], region["lon"])
        except Exception as exc:
            last_exc = exc
            print(f"  attempt {attempt}/{MAX_ATTEMPTS} failed for {region['name']}: {exc}")
            if attempt < MAX_ATTEMPTS:
                time.sleep(3 * attempt)  # 3s, 6s, 9s
    raise last_exc


def load_previous():
    """Returns the regions dict from the existing data.json, or {}."""
    if not os.path.exists("data.json"):
        return {}
    try:
        with open("data.json") as f:
            return json.load(f).get("regions", {}) or {}
    except Exception:
        return {}


def main():
    today_hobart = datetime.now(timezone(timedelta(hours=11))).strftime("%Y-%m-%d")
    previous = load_previous()
    out = {
        "generated_date": today_hobart,
        "regions": {},
    }
    failed = []
    for region in REGIONS:
        print(f"Fetching {region['name']}...")
        try:
            out["regions"][region["id"]] = fetch_with_retries(region)
        except Exception as exc:
            print(f"  FAILED for {region['name']} after {MAX_ATTEMPTS} attempts: {exc}")
            failed.append(region["name"])
            # Keep yesterday's forecast rather than writing null.
            out["regions"][region["id"]] = previous.get(region["id"])
        time.sleep(PAUSE_BETWEEN_REGIONS)

    with open("data.json", "w") as f:
        json.dump(out, f, indent=2)
    print("Wrote data.json")
    if failed:
        print("WARNING: could not refresh: " + ", ".join(failed))


if __name__ == "__main__":
    main()
