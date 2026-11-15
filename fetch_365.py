import csv
import math
import os
import time
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

BASE_URL = "https://api.openaq.org/v3"
COUNTRY_ISO = "PK"
HISTORY_DAYS = 365
PARAMETERS = {"pm25", "pm10", "pm1", "temperature", "relativehumidity"}
REQUEST_DELAY = 1.85
OUTPUT_FILE = "openaq_pakistan_hourly.csv"
DONE_FILE = "done_sensors.txt"
SKIPPED_FILE = "skipped_sensors.txt"
CITY_RADIUS_KM = 40

CITIES = {
    "Lahore": (31.5204, 74.3587), "Karachi": (24.8607, 67.0011),
    "Islamabad": (33.6844, 73.0479), "Rawalpindi": (33.5651, 73.0169),
    "Peshawar": (34.0151, 71.5249), "Faisalabad": (31.4504, 73.1350),
    "Multan": (30.1575, 71.5249), "Quetta": (30.1798, 66.9750),
    "Gujranwala": (32.1877, 74.1945),
}

FIELDS = [
    "city", "location_id", "location_name", "locality", "latitude", "longitude",
    "timezone", "provider", "owner", "is_mobile", "is_monitor",
    "sensor_id", "parameter", "units",
    "datetime_from_utc", "datetime_to_utc", "datetime_from_local",
    "value", "min", "max", "avg", "expected_count", "observed_count", "percent_complete",
]

session = requests.Session()


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


def nearest_city(lat, lon):
    if lat is None or lon is None:
        return "Unknown"
    name, dist = min(
        ((c, haversine_km(lat, lon, *xy)) for c, xy in CITIES.items()),
        key=lambda t: t[1],
    )
    return name if dist <= CITY_RADIUS_KM else "Other"


def get(url, params):
    for attempt in range(8):
        try:
            response = session.get(url, params=params, timeout=60)
        except requests.RequestException as error:
            print(f"  network error ({error}), retrying")
            time.sleep(5 * (attempt + 1))
            continue

        time.sleep(REQUEST_DELAY)
        if response.status_code == 200:
            return response.json()
        if response.status_code == 429:
            wait = int(response.headers.get("x-ratelimit-reset", 60)) + 1
            print(f"  rate limited, sleeping {wait}s")
            time.sleep(wait)
        elif response.status_code >= 500:
            time.sleep(5 * (attempt + 1))
        else:
            print(f"  error {response.status_code}: {response.text[:200]}")
            return None
    return None


def parse_utc(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00")) if text else None


def fetch_locations():
    locations = []
    page = 1
    while True:
        data = get(f"{BASE_URL}/locations", {"iso": COUNTRY_ISO, "limit": 1000, "page": page})
        if not data or not data.get("results"):
            break
        locations += data["results"]
        if len(data["results"]) < 1000:
            break
        page += 1
    return locations


def build_jobs(locations, start):
    jobs = []
    for location in locations:
        first_seen = parse_utc((location.get("datetimeFirst") or {}).get("utc"))
        last_seen = parse_utc((location.get("datetimeLast") or {}).get("utc"))
        if last_seen and last_seen < start:
            continue

        coords = location.get("coordinates") or {}
        lat, lon = coords.get("latitude"), coords.get("longitude")
        info = {
            "location_id": location["id"],
            "location_name": location.get("name"),
            "locality": location.get("locality"),
            "city": nearest_city(lat, lon),
            "latitude": lat,
            "longitude": lon,
            "timezone": location.get("timezone"),
            "provider": (location.get("provider") or {}).get("name"),
            "owner": (location.get("owner") or {}).get("name"),
            "is_mobile": location.get("isMobile"),
            "is_monitor": location.get("isMonitor"),
        }
        for sensor in location.get("sensors", []):
            parameter = sensor.get("parameter") or {}
            if parameter.get("name") in PARAMETERS:
                jobs.append({
                    "info": info,
                    "sensor_id": sensor["id"],
                    "parameter": parameter["name"],
                    "units": parameter.get("units"),
                    "first_seen": first_seen,
                })
    return jobs


def make_row(job, result):
    period = result.get("period") or {}
    summary = result.get("summary") or {}
    coverage = result.get("coverage") or {}
    time_from = period.get("datetimeFrom") or {}
    time_to = period.get("datetimeTo") or {}
    return {
        **job["info"],
        "sensor_id": job["sensor_id"],
        "parameter": job["parameter"],
        "units": job["units"],
        "datetime_from_utc": time_from.get("utc"),
        "datetime_to_utc": time_to.get("utc"),
        "datetime_from_local": time_from.get("local"),
        "value": result.get("value"),
        "min": summary.get("min"),
        "max": summary.get("max"),
        "avg": summary.get("avg"),
        "expected_count": coverage.get("expectedCount"),
        "observed_count": coverage.get("observedCount"),
        "percent_complete": coverage.get("percentComplete"),
    }


def collect_sensor(job, start, end, writer):
    rows = 0
    page = 1
    while True:
        try:
            data = get(
                f"{BASE_URL}/sensors/{job['sensor_id']}/hours",
                {
                    "datetime_from": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "datetime_to": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "limit": 1000,
                    "page": page,
                },
            )
        except KeyboardInterrupt:
            choice = input("\n  paused: [s] skip this sensor, [q] quit, Enter to resume: ").strip().lower()
            if choice == "q":
                return rows, "quit"
            if choice == "s":
                return rows, "skipped"
            continue

        if data is None:
            return rows, "failed"

        results = data.get("results", [])
        for result in results:
            writer.writerow(make_row(job, result))
        rows += len(results)
        if len(results) < 1000:
            return rows, "done"
        page += 1


def main():
    load_dotenv()
    api_key = os.environ.get("OPENAQ_API_KEY")
    if not api_key:
        raise SystemExit("OPENAQ_API_KEY is not set")
    session.headers.update({"X-API-Key": api_key})

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=HISTORY_DAYS)

    print("fetching Pakistan locations")
    locations = fetch_locations()
    print(f"found {len(locations)} locations")

    jobs = build_jobs(locations, start)
    done = set()
    if os.path.exists(DONE_FILE):
        with open(DONE_FILE) as f:
            done = set(f.read().split())
    print(f"{len(jobs)} sensors to fetch ({len(done)} already done)")

    is_new_file = not os.path.exists(OUTPUT_FILE)
    with open(OUTPUT_FILE, "a", newline="", encoding="utf-8") as data_file, \
         open(DONE_FILE, "a") as done_file:
        writer = csv.DictWriter(data_file, fieldnames=FIELDS)
        if is_new_file:
            writer.writeheader()

        for number, job in enumerate(jobs, 1):
            if str(job["sensor_id"]) in done:
                continue

            info = job["info"]
            print(f"[{number}/{len(jobs)}] {info['city']} | {info['location_name']} | {job['parameter']}")

            sensor_start = max(start, job["first_seen"]) if job["first_seen"] else start
            rows, status = collect_sensor(job, sensor_start, now, writer)

            if status == "quit":
                data_file.flush()
                print("quitting, rerun to resume")
                return

            if status in ("done", "skipped"):
                data_file.flush()
                done_file.write(f"{job['sensor_id']}\n")
                done_file.flush()

            if status == "skipped":
                with open(SKIPPED_FILE, "a") as skipped_file:
                    skipped_file.write(f"{job['sensor_id']}\t{info['location_name']}\t{job['parameter']}\n")
                print(f"   skipped by you ({rows} rows already written)")
            else:
                print(f"   {rows} rows")

    print(f"\ndone, output in {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
