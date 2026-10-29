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

# Real-world coordinates for every location offered on the calculator
# (Tasmania pins from the Google Earth file).
REGIONS = [
    {"id": "smithton", "name": "Smithton", "lat": -40.84177, "lon": 145.12585, "tz": "Australia/Hobart"},
    {"id": "table-cape", "name": "Table Cape / Wynyard", "lat": -40.95675, "lon": 145.71819, "tz": "Australia/Hobart"},
    {"id": "sassafras", "name": "Sassafras / Devonport", "lat": -41.29055, "lon": 146.50511, "tz": "Australia/Hobart"},
    {"id": "waterhouse", "name": "Waterhouse", "lat": -40.93138, "lon": 147.61799, "tz": "Australia/Hobart"},
    {"id": "scottsdale", "name": "Scottsdale", "lat": -41.16065, "lon": 147.51704, "tz": "Australia/Hobart"},
    {"id": "cressy", "name": "Cressy", "lat": -41.68995, "lon": 147.07940, "tz": "Australia/Hobart"},
    {"id": "campbell-town", "name": "Campbell Town", "lat": -41.92882, "lon": 147.49351, "tz": "Australia/Hobart"},
    {"id": "bothwell", "name": "Bothwell", "lat": -42.38417, "lon": 147.00770, "tz": "Australia/Hobart"},
    {"id": "marion-bay", "name": "Marion Bay", "lat": -42.82031, "lon": 147.85862, "tz": "Australia/Hobart"},
    {"id": "lileah", "name": "Lileah", "lat": -40.95343, "lon": 145.16153, "tz": "Australia/Hobart"},
    {"id": "sisters-creek", "name": "Sisters Creek", "lat": -40.96282, "lon": 145.55378, "tz": "Australia/Hobart"},
    {"id": "yolla", "name": "Yolla", "lat": -41.12568, "lon": 145.71623, "tz": "Australia/Hobart"},
    {"id": "sheffield", "name": "Sheffield", "lat": -41.38213, "lon": 146.32468, "tz": "Australia/Hobart"},
    {"id": "deloraine", "name": "Deloraine", "lat": -41.52165, "lon": 146.64720, "tz": "Australia/Hobart"},
    {"id": "hagley", "name": "Hagley", "lat": -41.52596, "lon": 146.89845, "tz": "Australia/Hobart"},
    {"id": "poatina", "name": "Poatina", "lat": -41.79582, "lon": 146.96105, "tz": "Australia/Hobart"},
    {"id": "macquarie-barton", "name": "Macquarie Rd/Barton Rd", "lat": -41.86013, "lon": 147.24645, "tz": "Australia/Hobart"},
    {"id": "winnaleah", "name": "Winnaleah", "lat": -41.09854, "lon": 147.82624, "tz": "Australia/Hobart"},
    {"id": "branxholm", "name": "Branxholm", "lat": -41.16832, "lon": 147.73651, "tz": "Australia/Hobart"},
    {"id": "pyengana", "name": "Pyengana", "lat": -41.28880, "lon": 148.00670, "tz": "Australia/Hobart"}
]

API_URL = "https://api.open-meteo.com/v1/forecast"
MAX_ATTEMPTS = 4          # tries per region
PAUSE_BETWEEN_REGIONS = 1.5  # seconds


def fetch_region_week(lat, lon, tz):
    """Calls Open-Meteo for one location and returns a 7-day list of
    {date, eto, rain} — the exact shape the calculator expects."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "et0_fao_evapotranspiration,precipitation_sum",
        "timezone": tz,
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
            return fetch_region_week(region["lat"], region["lon"], region.get("tz", "Australia/Hobart"))
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
