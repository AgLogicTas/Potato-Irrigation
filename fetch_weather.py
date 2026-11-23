#!/usr/bin/env python3
"""
Fetches a 7-day ETo / rainfall forecast for each Ag Logic potato region from
Open-Meteo (free, no API key needed) and writes data.json.

Run automatically by .github/workflows/update-weather.yml. You can also run it
yourself with: python3 fetch_weather.py

How it works (changed Nov 2026 after Dean/Newlyn went stale):
- ALL locations are requested in ONE call to Open-Meteo (instead of one call
  per location), so there is only one connection that can time out.
- That call is retried up to 6 times with growing pauses and a long timeout.
- If the one big call still fails, it falls back to one call per location.
- If a location still can't be fetched, its previous forecast is kept in
  data.json (so the Power Automate flow never sees null) BUT the script then
  exits with an error, so the GitHub run turns RED instead of looking fine.
  The data.json file is still saved/committed first.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

# Real-world coordinates for every location offered on the calculator.
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
    {"id": "pyengana", "name": "Pyengana", "lat": -41.28880, "lon": 148.00670, "tz": "Australia/Hobart"},
]

API_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT = 60              # seconds to wait for Open-Meteo (was 30)
BATCH_ATTEMPTS = 6        # tries for the one-call-for-everything request
SINGLE_ATTEMPTS = 4       # tries per location in the fallback
PAUSE_BETWEEN_SINGLES = 2 # seconds
DAILY = "et0_fao_evapotranspiration,precipitation_sum"


def call_api(lats, lons, tz):
    params = {
        "latitude": ",".join(str(x) for x in lats),
        "longitude": ",".join(str(x) for x in lons),
        "daily": DAILY,
        "timezone": tz,
        "forecast_days": 7,
    }
    url = API_URL + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:
        payload = json.load(resp)
    # One location returns an object; several return a list (same order).
    return payload if isinstance(payload, list) else [payload]


def to_week(item):
    daily = item["daily"]
    dates = daily["time"]
    eto = daily["et0_fao_evapotranspiration"]
    rain = daily["precipitation_sum"]
    week = [{
        "date": dates[i],
        "eto": round(eto[i], 2) if eto[i] is not None else None,
        "rain": round(rain[i], 2) if rain[i] is not None else None,
    } for i in range(len(dates))]
    # A week with any missing value counts as a failure so it gets retried.
    if len(week) < 7 or any(d["eto"] is None or d["rain"] is None for d in week):
        raise ValueError("Open-Meteo returned incomplete data")
    return week


def with_retries(fn, attempts, label):
    last = None
    for n in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:
            last = exc
            print(f"  attempt {n}/{attempts} failed for {label}: {exc}")
            if n < attempts:
                time.sleep(5 * n)  # 5s, 10s, 15s ...
    raise last


def load_previous():
    if not os.path.exists("data.json"):
        return {}
    try:
        with open("data.json") as f:
            return json.load(f).get("regions", {}) or {}
    except Exception:
        return {}


def main():
    previous = load_previous()
    regions_out = {}
    failed = []

    # Group by timezone so each request has one timezone.
    groups = {}
    for r in REGIONS:
        groups.setdefault(r.get("tz", "Australia/Hobart"), []).append(r)

    for tz, regs in groups.items():
        print(f"Fetching {len(regs)} locations in one request ({tz})...")
        batch = None
        try:
            batch = with_retries(
                lambda: call_api([r["lat"] for r in regs], [r["lon"] for r in regs], tz),
                BATCH_ATTEMPTS, "the batch request")
            if len(batch) != len(regs):
                raise ValueError(f"expected {len(regs)} locations, got {len(batch)}")
        except Exception as exc:
            print(f"  batch request failed ({exc}); falling back to one request per location")
            batch = None

        for i, r in enumerate(regs):
            week = None
            if batch is not None:
                try:
                    week = to_week(batch[i])
                except Exception as exc:
                    print(f"  {r['name']}: bad data in batch ({exc})")
            if week is None:
                print(f"Fetching {r['name']} on its own...")
                try:
                    week = with_retries(
                        lambda: to_week(call_api([r["lat"]], [r["lon"]], tz)[0]),
                        SINGLE_ATTEMPTS, r["name"])
                except Exception as exc:
                    print(f"  FAILED for {r['name']}: {exc}")
                    failed.append(r["name"])
                    week = previous.get(r["id"])  # keep yesterday's, never null-out
                time.sleep(PAUSE_BETWEEN_SINGLES)
            regions_out[r["id"]] = week

    first_tz = REGIONS[0].get("tz", "Australia/Hobart")
    out = {
        "generated_date": datetime.now(ZoneInfo(first_tz)).strftime("%Y-%m-%d"),
        "regions": regions_out,
    }
    with open("data.json", "w") as f:
        json.dump(out, f, indent=2)
    print("Wrote data.json")

    if failed:
        print("ERROR: could not refresh (old forecast kept): " + ", ".join(failed))
        sys.exit(1)  # makes the GitHub run go RED so it can't fail quietly
    print("All locations refreshed.")


if __name__ == "__main__":
    main()
