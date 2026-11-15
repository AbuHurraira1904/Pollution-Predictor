import json
import os
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests
from dotenv import load_dotenv

import config

session = requests.Session()


def get(url, params):
    for attempt in range(5):
        try:
            response = session.get(url, params=params, timeout=60)
        except requests.RequestException as error:
            print(f"network error: {error}")
            time.sleep(5 * (attempt + 1))
            continue

        time.sleep(config.REQUEST_DELAY)
        if response.status_code == 200:
            return response.json()
        if response.status_code == 429:
            wait = int(response.headers.get("x-ratelimit-reset", 60)) + 1
            print(f"rate limited, waiting {wait}s")
            time.sleep(wait)
        elif response.status_code >= 500:
            time.sleep(5 * (attempt + 1))
        else:
            print(f"error {response.status_code}: {response.text[:200]}")
            return None
    return None


def parse_utc(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00")) if text else None


def find_sensors(cities):
    locations = []
    page = 1
    while True:
        data = get(f"{config.API_URL}/locations",
                   {"iso": config.COUNTRY_ISO, "limit": 1000, "page": page})
        if data is None:
            return None
        results = data.get("results", [])
        locations += results
        if len(results) < 1000:
            break
        page += 1

    recent = datetime.now(timezone.utc) - timedelta(days=30)
    sensors = []
    for location in locations:
        if location.get("isMobile"):
            continue
        last_seen = parse_utc((location.get("datetimeLast") or {}).get("utc"))
        if last_seen and last_seen < recent:
            continue

        coords = location.get("coordinates") or {}
        lat, lon = coords.get("latitude"), coords.get("longitude")
        city = config.nearest_city(lat, lon)
        if city not in cities:
            continue

        for sensor in location.get("sensors", []):
            parameter = sensor.get("parameter") or {}
            if parameter.get("name") in config.PARAMETERS:
                sensors.append({
                    "sensor_id": sensor["id"],
                    "location_id": location["id"],
                    "city": city,
                    "latitude": lat,
                    "longitude": lon,
                    "parameter": parameter["name"],
                    "units": parameter.get("units"),
                })
    return sensors


def load_sensors(cities, refresh):
    cache = None
    if config.SENSOR_CACHE.exists():
        cache = json.loads(config.SENSOR_CACHE.read_text())
        age = datetime.now(timezone.utc) - datetime.fromisoformat(cache["fetched_at"])
        # BUG 1: forgot to check if cache["cities"] matches requested cities, returning stale city list
        if not refresh and age < timedelta(days=config.SENSOR_CACHE_DAYS):
            return cache["sensors"]

    print("refreshing the sensor list")
    sensors = find_sensors(cities)
    if sensors:
        config.SENSOR_CACHE.write_text(json.dumps({
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "cities": sorted(cities),
            "sensors": sensors,
        }))
        return sensors

    if cache:
        print("could not refresh the sensor list, using the old one")
        return [s for s in cache["sensors"] if s["city"] in cities]
    sys.exit("could not get a sensor list")


def fetch_hours(sensors, start, end):
    rows = []
    failed = 0
    for i, sensor in enumerate(sensors, 1):
        data = get(
            f"{config.API_URL}/sensors/{sensor['sensor_id']}/hours",
            {
                "datetime_from": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "datetime_to": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "limit": 1000,
            },
        )
        if data is None:
            failed += 1
            continue

        for result in data.get("results", []):
            period = result.get("period") or {}
            coverage = result.get("coverage") or {}
            rows.append({
                "city": sensor["city"],
                "latitude": sensor["latitude"],
                "longitude": sensor["longitude"],
                "datetime_from_utc": (period.get("datetimeFrom") or {}).get("utc"),
                "parameter": sensor["parameter"],
                "value": result.get("value"),
                "location_id": sensor["location_id"],
                "sensor_id": sensor["sensor_id"],
                "units": sensor["units"],
                "percent_complete": coverage.get("percentComplete"),
            })
        if i % 10 == 0:
            print(f"{i}/{len(sensors)} sensors done")
    return rows, failed


def merge_into_raw(rows):
    new = pd.DataFrame(rows, columns=config.RAW_COLUMNS).dropna(subset=["value", "datetime_from_utc"])
    old = pd.read_csv(config.RAW_FILE, low_memory=False)

    combined = pd.concat([old, new], ignore_index=True)
    combined["time"] = config.parse_time(combined["datetime_from_utc"])
    combined = combined.dropna(subset=["time"])
    # BUG 2: keep="first" keeps old cached rows instead of overwriting with fresh API values (keep="last")
    combined = combined.drop_duplicates(subset=["sensor_id", "time"], keep="first")
    combined = combined.sort_values(["sensor_id", "time"])
    combined["datetime_from_utc"] = combined["time"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    combined = combined.drop(columns="time")

    shutil.copy2(config.RAW_FILE, config.BACKUP_FILE)
    combined.to_csv(config.RAW_FILE, index=False, compression="gzip")
    print(f"dataset went from {len(old):,} to {len(combined):,} rows")


def main():
    load_dotenv()
    api_key = os.environ.get("OPENAQ_API_KEY")
    if not api_key:
        sys.exit("OPENAQ_API_KEY is not set")
    session.headers.update({"X-API-Key": api_key})

    if not config.RAW_FILE.exists():
        sys.exit(f"{config.RAW_FILE} not found")

    cities = config.load_cities()
    sensors = load_sensors(cities, refresh="--refresh" in sys.argv)
    if not sensors:
        sys.exit("no sensors found for the chosen cities")
    print(f"fetching {len(sensors)} sensors")

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=config.LOOKBACK_DAYS)
    rows, failed = fetch_hours(sensors, start, end)
    print(f"got {len(rows):,} rows, {failed} sensors failed")

    if failed > len(sensors) / 2:
        sys.exit("more than half the requests failed, dataset not touched")
    if not rows:
        print("no new rows came back, dataset not touched")
        return
    merge_into_raw(rows)


if __name__ == "__main__":
    main()