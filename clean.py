import os

import numpy as np
import pandas as pd

import config

COLUMNS = ["city", "datetime_from_utc", "parameter", "value",
           "units", "percent_complete", "location_id"]

LIMITS = {
    "pm25": (0, 1000),
    "pm10": (0, 2000),
    "temperature": (-10, 55),
    "relativehumidity": (0, 100),
}

MIN_HOUR_COMPLETE = 50
MIN_PM_HOURS = 18
MIN_WEATHER_HOURS = 12


def load_raw():
    df = pd.read_csv(config.RAW_FILE, usecols=COLUMNS, low_memory=False)
    df["time"] = config.parse_time(df["datetime_from_utc"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.dropna(subset=["time", "value"])


def clean_hourly(raw):
    df = raw[raw["parameter"].isin(LIMITS)].copy()

    units = df["units"].astype(str).str.lower().str.replace("°", "", regex=False).str.strip()
    in_fahrenheit = (df["parameter"] == "temperature") & units.isin(["f", "degf", "fahrenheit"])
    df.loc[in_fahrenheit, "value"] = (df.loc[in_fahrenheit, "value"] - 32) * 5 / 9

    low = df["parameter"].map({name: limit[0] for name, limit in LIMITS.items()})
    high = df["parameter"].map({name: limit[1] for name, limit in LIMITS.items()})
    df = df[(df["value"] >= low) & (df["value"] <= high)]

    complete = pd.to_numeric(df["percent_complete"], errors="coerce")
    df = df[complete.isna() | (complete >= MIN_HOUR_COMPLETE)]

    print(f"kept {len(df):,} of {len(raw):,} hourly rows")
    return df

def daily_by_city(raw):
    hourly = clean_hourly(raw)
    hourly = hourly.groupby(["city", "time", "parameter"])["value"].median().unstack("parameter")
    hourly = hourly.reindex(columns=list(LIMITS)).reset_index()

    local_time = hourly["time"] + pd.Timedelta(hours=5)
    hourly["day"] = local_time.dt.tz_localize(None).dt.normalize()

    grouped = hourly.groupby(["city", "day"])
    daily = pd.DataFrame({
        "pm25_mean": grouped["pm25"].mean(),
        "pm25_max": grouped["pm25"].max(),
        "pm25_hours": grouped["pm25"].count(),
        "pm10_mean": grouped["pm10"].mean(),
        "pm10_hours": grouped["pm10"].count(),
        "temp_mean": grouped["temperature"].mean(),
        "temp_min": grouped["temperature"].min(),
        "temp_max": grouped["temperature"].max(),
        "temp_hours": grouped["temperature"].count(),
        "rh_mean": grouped["relativehumidity"].mean(),
        "rh_hours": grouped["relativehumidity"].count(),
    }).reset_index()

    daily.loc[daily["pm25_hours"] < MIN_PM_HOURS, ["pm25_mean", "pm25_max"]] = np.nan
    daily.loc[daily["pm10_hours"] < MIN_PM_HOURS, "pm10_mean"] = np.nan
    daily.loc[daily["temp_hours"] < MIN_WEATHER_HOURS, ["temp_mean", "temp_min", "temp_max"]] = np.nan
    daily.loc[daily["rh_hours"] < MIN_WEATHER_HOURS, "rh_mean"] = np.nan

    hour_columns = ["pm25_hours", "pm10_hours", "temp_hours", "rh_hours"]
    last_day = config.last_complete_day()
    frames = []
    for city, rows in daily.groupby("city"):
        rows = rows[rows["day"] <= last_day].drop(columns="city").set_index("day").sort_index()
        if rows.empty:
            continue
        calendar = pd.date_range(rows.index.min(), last_day, freq="D")
        rows = rows.reindex(calendar)
        rows[hour_columns] = rows[hour_columns].fillna(0)
        rows.insert(0, "city", city)
        rows.index.name = "date"
        frames.append(rows.reset_index())

    if not frames:
        raise SystemExit("no usable data after cleaning")
    return pd.concat(frames, ignore_index=True)