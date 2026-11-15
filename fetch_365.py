import csv
import math
import os
import time
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

load_dotenv()  # reads .env from the current working directory

# ---------------- CONFIG ----------------
API_KEY = os.environ["OPENAQ_API_KEY"]  # export OPENAQ_API_KEY=...
BASE = "https://api.openaq.org/v3"
COUNTRY_ISO = "PK"
HISTORY_DAYS = 365  # 1 year max
PARAMETERS = {"pm25", "pm10", "pm1", "temperature", "relativehumidity"}  # trim to speed up
MIN_SECONDS_BETWEEN_REQUESTS = 1.85  # stays under 60 req/min
OUT_CSV = "openaq_pakistan_hourly.csv"
DONE_FILE = "done_sensors.txt"  # lets you resume if the script dies
# ----------------------------------------

# Approximate city centres, used to build a clean `city` grouping column
CITIES = {
    "Lahore": (31.5204, 74.3587), "Karachi": (24.8607, 67.0011),
    "Islamabad": (33.6844, 73.0479), "Rawalpindi": (33.5651, 73.0169),
    "Peshawar": (34.0151, 71.5249), "Faisalabad": (31.4504, 73.1350),
    "Multan": (30.1575, 71.5249), "Quetta": (30.1798, 66.9750),
    "Gujranwala": (32.1877, 74.1945),
}
CITY_RADIUS_KM = 40

session = requests.Session()
session.headers.update({"X-API-Key": API_KEY})
_last_request = 0.0


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
    """GET with throttling and 429/5xx handling."""
    global _last_request
    for attempt in range(8):
        wait = MIN_SECONDS_BETWEEN_REQUESTS - (time.time() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.time()
        try:
            r = session.get(url, params=params, timeout=60)
        except requests.RequestException as e:
            print(f"  network error ({e}), retrying...")
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429:
            reset = int(r.headers.get("x-ratelimit-reset", 60))
            print(f"  rate limited, sleeping {reset + 1}s")
            time.sleep(reset + 1)
            continue
        if r.status_code >= 500:
            time.sleep(5 * (attempt + 1))
            continue
        print(f"  error {r.status_code}: {r.text[:200]}")
        return None
    return None


def parse_dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def fetch_locations():
    locations, page = [], 1
    while True:
        data = get(f"{BASE}/locations", {"iso": COUNTRY_ISO, "limit": 1000, "page": page})
        if not data or not data.get("results"):
            break
        locations.extend(data["results"])
        if len(data["results"]) < 1000:
            break
        page += 1
    return locations


def main():
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=HISTORY_DAYS)

    print("Fetching Pakistan locations...")
    locations = fetch_locations()
    print(f"Found {len(locations)} locations")

    # Build sensor job list, skipping sensors with no data in our window
    jobs = []
    for loc in locations:
        first = parse_dt((loc.get("datetimeFirst") or {}).get("utc"))
        last = parse_dt((loc.get("datetimeLast") or {}).get("utc"))
        if last and last < start:
            continue
        coords = loc.get("coordinates") or {}
        lat, lon = coords.get("latitude"), coords.get("longitude")
        meta = {
            "location_id": loc["id"],
            "location_name": loc.get("name"),
            "locality": loc.get("locality"),
            "city": nearest_city(lat, lon),
            "latitude": lat,
            "longitude": lon,
            "timezone": loc.get("timezone"),
            "provider": (loc.get("provider") or {}).get("name"),
            "owner": (loc.get("owner") or {}).get("name"),
            "is_mobile": loc.get("isMobile"),
            "is_monitor": loc.get("isMonitor"),
        }
        for s in loc.get("sensors", []):
            p = s.get("parameter") or {}
            if p.get("name") in PARAMETERS:
                jobs.append((meta, s["id"], p["name"], p.get("units"), first))

    done = set()
    if os.path.exists(DONE_FILE):
        done = set(open(DONE_FILE).read().split())

    print(f"{len(jobs)} sensors to fetch ({len(done)} already done)")

    fields = [
        "city", "location_id", "location_name", "locality", "latitude", "longitude",
        "timezone", "provider", "owner", "is_mobile", "is_monitor",
        "sensor_id", "parameter", "units",
        "datetime_from_utc", "datetime_to_utc", "datetime_from_local",
        "value", "min", "max", "avg", "expected_count", "observed_count", "percent_complete",
    ]
    new_file = not os.path.exists(OUT_CSV)
    with open(OUT_CSV, "a", newline="", encoding="utf-8") as f, open(DONE_FILE, "a") as done_f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new_file:
            w.writeheader()

        for i, (meta, sensor_id, param, units, first) in enumerate(jobs, 1):
            if str(sensor_id) in done:
                continue
            sensor_start = max(start, first) if first else start
            print(f"[{i}/{len(jobs)}] {meta['city']} | {meta['location_name']} | {param}")

            rows, page = 0, 1
            skipped = False
            while True:
                try:
                    data = get(
                        f"{BASE}/sensors/{sensor_id}/hours",
                        {
                            "datetime_from": sensor_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "datetime_to": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "limit": 1000,
                            "page": page,
                        },
                    )
                except KeyboardInterrupt:
                    choice = input(
                        "\n  Paused. [s] skip this sensor, [q] quit, Enter to resume: "
                    ).strip().lower()
                    if choice == "q":
                        f.flush()
                        print("Quitting. Rerun to resume.")
                        return
                    if choice == "s":
                        skipped = True
                        break
                    continue  # resume: retries the same page

                if data is None:
                    break  # don't mark done; will retry on next run
                results = data.get("results", [])
                for r in results:
                    period = r.get("period") or {}
                    summ = r.get("summary") or {}
                    cov = r.get("coverage") or {}
                    w.writerow({
                        **meta,
                        "sensor_id": sensor_id,
                        "parameter": param,
                        "units": units,
                        "datetime_from_utc": (period.get("datetimeFrom") or {}).get("utc"),
                        "datetime_to_utc": (period.get("datetimeTo") or {}).get("utc"),
                        "datetime_from_local": (period.get("datetimeFrom") or {}).get("local"),
                        "value": r.get("value"),
                        "min": summ.get("min"),
                        "max": summ.get("max"),
                        "avg": summ.get("avg"),
                        "expected_count": cov.get("expectedCount"),
                        "observed_count": cov.get("observedCount"),
                        "percent_complete": cov.get("percentComplete"),
                    })
                rows += len(results)
                if len(results) < 1000:
                    f.flush()
                    done_f.write(f"{sensor_id}\n")
                    done_f.flush()
                    break
                page += 1

            if skipped:
                f.flush()
                done_f.write(f"{sensor_id}\n")  # so a rerun doesn't revisit it
                done_f.flush()
                with open("skipped_sensors.txt", "a") as sk:
                    sk.write(f"{sensor_id}\t{meta['location_name']}\t{param}\n")
                print(f"   -> skipped by user ({rows} rows already written)")
            else:
                print(f"   -> {rows} rows")

    print(f"\nDone. Output: {OUT_CSV}")


if __name__ == "__main__":
    main()