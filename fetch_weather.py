#!/usr/bin/env python3
"""
Fetches a 7-day ETo / rainfall forecast for each Ag Logic potato region from
Open-Meteo (free, no API key needed) and writes data.json.

This is run automatically by .github/workflows/update-weather.yml on a daily
schedule. You can also run it yourself locally with: python3 fetch_weather.py
"""
import json
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
    return week


def main():
    today_hobart = datetime.now(timezone(timedelta(hours=11))).strftime("%Y-%m-%d")
    out = {
        "generated_date": today_hobart,
        "regions": {},
    }
    for region in REGIONS:
        print(f"Fetching {region['name']}...")
        try:
            out["regions"][region["id"]] = fetch_region_week(region["lat"], region["lon"])
        except Exception as exc:
            print(f"  FAILED for {region['name']}: {exc}")
            out["regions"][region["id"]] = None

    with open("data.json", "w") as f:
        json.dump(out, f, indent=2)
    print("Wrote data.json")


if __name__ == "__main__":
    main()
