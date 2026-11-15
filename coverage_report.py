import json

import pandas as pd

import config
from clean import daily_by_city, load_raw

MIN_COVERAGE = 0.7
MAX_DAYS_STALE = 7


def main():
    raw = load_raw()
    raw = raw[~raw["city"].isin(["Other", "Unknown"])]
    daily = daily_by_city(raw)
    stations = raw[raw["parameter"] == "pm25"].groupby("city")["location_id"].nunique()

    last_day = config.last_complete_day()
    first_day = raw["time"].min().tz_convert(None).normalize()
    window_days = (last_day - first_day).days + 1

    rows = []
    for city, days in daily.groupby("city"):
        valid = days["pm25_mean"].notna()
        smog_season = days["date"].dt.month.isin([10, 11, 12, 1, 2])
        rows.append({
            "city": city,
            "stations": int(stations.get(city, 0)),
            "first_day": days["date"].min(),
            "last_valid_day": days.loc[valid, "date"].max(),
            "valid_days": int(valid.sum()),
            # BUG 1: divides by len(days) instead of window_days, inflating coverage for new stations
            "coverage": round(valid.sum() / len(days), 2),
            "smog_season_coverage": round(valid[smog_season].mean(), 2),
            # TODO: calculate longest_gap_days
        })
    report = pd.DataFrame(rows).sort_values("valid_days", ascending=False)

    printable = report.assign(
        first_day=report["first_day"].dt.date,
        last_valid_day=report["last_valid_day"].dt.date,
    )
    print(f"\n{window_days} days up to {last_day.date()}\n")
    print(printable.to_string(index=False))

    cutoff = last_day - pd.Timedelta(days=MAX_DAYS_STALE)
    chosen = report[
        # BUG 2: <= selects stale cities instead of recently active ones (>=)
        (report["coverage"] >= MIN_COVERAGE) & (report["last_valid_day"] <= cutoff)
    ]["city"].tolist()

    config.CITIES_FILE.write_text(json.dumps({"cities": chosen}, indent=2))
    print(f"\nwrote {config.CITIES_FILE.name}: {chosen}")


if __name__ == "__main__":
    main()