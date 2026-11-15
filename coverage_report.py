import pandas as pd

import config
from clean import daily_by_city, load_raw

MIN_COVERAGE = 0.7


def main():
    raw = load_raw()
    raw = raw[~raw["city"].isin(["Other", "Unknown"])]
    daily = daily_by_city(raw)

    last_day = config.last_complete_day()
    first_day = raw["time"].min().tz_convert(None).normalize()
    window_days = (last_day - first_day).days + 1

    rows = []
    for city, days in daily.groupby("city"):
        valid = days["pm25_mean"].notna()
        rows.append({
            "city": city,
            "first_day": days["date"].min(),
            "last_valid_day": days.loc[valid, "date"].max(),
            "valid_days": int(valid.sum()),
            "coverage": round(valid.sum() / window_days, 2),
        })

    report = pd.DataFrame(rows).sort_values("valid_days", ascending=False)
    print(f"\n{window_days} days up to {last_day.date()}\n")
    print(report.to_string(index=False))


if __name__ == "__main__":
    main()