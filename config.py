import json
import math
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"

RAW_FILE = DATA_DIR / "openaq_pakistan_slim.csv.gz"
BACKUP_FILE = DATA_DIR / "raw_backup.csv.gz"
CLEAN_FILE = DATA_DIR / "clean_daily.csv.gz"
SENSOR_CACHE = DATA_DIR / "sensor_cache.json"
CITIES_FILE = ROOT / "cities.json"

API_URL = "https://api.openaq.org/v3"
COUNTRY_ISO = "PK"
PARAMETERS = {"pm25", "pm10", "temperature", "relativehumidity"}
LOOKBACK_DAYS = 2
REQUEST_DELAY = 1.1
SENSOR_CACHE_DAYS = 7

RAW_COLUMNS = [
    "city", "latitude", "longitude", "datetime_from_utc", "parameter", "value",
    "location_id", "sensor_id", "units", "percent_complete",
]

CITIES = {
    "Lahore": (31.5204, 74.3587), "Karachi": (24.8607, 67.0011),
    "Islamabad": (33.6844, 73.0479), "Rawalpindi": (33.5651, 73.0169),
    "Peshawar": (34.0151, 71.5249), "Faisalabad": (31.4504, 73.1350),
    "Multan": (30.1575, 71.5249), "Quetta": (30.1798, 66.9750),
    "Gujranwala": (32.1877, 74.1945), "Sialkot": (32.4945, 74.5229),
    "Hyderabad": (25.3960, 68.3578),
}
CITY_RADIUS_KM = 40


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


def parse_time(series):
    return pd.to_datetime(series, utc=True, format="ISO8601", errors="coerce")


def local_now():
    return pd.Timestamp.now("UTC").tz_localize(None) + pd.Timedelta(hours=5)


def last_complete_day():
    return local_now().normalize() - pd.Timedelta(days=1)


def load_cities():
    if not CITIES_FILE.exists():
        raise SystemExit("cities.json not found, run coverage_report.py first")
    cities = json.loads(CITIES_FILE.read_text())["cities"]
    if not cities:
        raise SystemExit("cities.json is empty, rerun coverage_report.py or edit it by hand")
    return cities
