import pandas as pd

SOURCE = "openaq_pakistan_hourly.csv"
OUTPUT = "openaq_pakistan_slim.csv"
CHUNK_SIZE = 500_000

KEEP = [
    "city",
    "latitude",
    "longitude",
    "datetime_from_utc",
    "parameter",
    "value",
    "location_id",
    "sensor_id",
    "units",
    "percent_complete",
]

rows_read = rows_written = mobile_dropped = empty_dropped = 0
first_chunk = True

for chunk in pd.read_csv(SOURCE, usecols=KEEP + ["is_mobile"], chunksize=CHUNK_SIZE, low_memory=False):
    rows_read += len(chunk)

    is_mobile = chunk["is_mobile"].astype(str).str.strip().str.lower() == "true"
    mobile_dropped += int(is_mobile.sum())
    chunk = chunk[~is_mobile]

    has_value = chunk["value"].notna()
    empty_dropped += int((~has_value).sum())
    chunk = chunk[has_value]

    chunk[KEEP].to_csv(OUTPUT, mode="w" if first_chunk else "a", header=first_chunk, index=False)
    first_chunk = False
    rows_written += len(chunk)
    print(f"{rows_read:,} rows read, {rows_written:,} written")

print(f"done: {rows_written:,} rows -> {OUTPUT}")
print(f"dropped {mobile_dropped:,} mobile-station rows and {empty_dropped:,} rows with no value")
