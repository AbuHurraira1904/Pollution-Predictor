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
