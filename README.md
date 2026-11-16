# Pollution Predictor

Fetches daily air quality data for Pakistani cities from the OpenAQ API, cleans it, and stores it as a compressed CSV.

## Setup

```bash
pip install -r requirements.txt
```

Create a `.env` file with your OpenAQ API key:

```
OPENAQ_API_KEY=your_key_here
```

## Usage

**First-time setup** — fetch a full year of history and build the city list:

```bash
python fetch_365.py
python coverage_report.py
```

**Daily update** — fetch recent data and re-clean:

```bash
python run_daily.py
```

This runs `fetch_recent.py` → `clean.py` in sequence. Use `--skip-fetch` to only re-run cleaning.

## Data

Cleaned output lands at `data/clean_daily.csv.gz`. Each row is one city × one day with columns:

| Column | Description |
|---|---|
| `city` | City name |
| `date` | Date (UTC) |
| `pm25_mean` / `pm25_max` | Daily PM2.5 (µg/m³) |
| `pm10_mean` | Daily PM10 (µg/m³) |
| `temp_mean` / `temp_min` / `temp_max` | Temperature (°C) |
| `rh_mean` | Relative humidity (%) |
| `pm25_hours` | Hours of PM2.5 coverage that day |

Cities covered: Lahore, Karachi, Islamabad, Rawalpindi, Peshawar, Faisalabad, Multan, Quetta, Gujranwala, Sialkot, Hyderabad.

## Files

| File | Purpose |
|---|---|
| `fetch_365.py` | One-time historical fetch (365 days) |
| `fetch_recent.py` | Incremental fetch (last few days) |
| `clean.py` | Aggregates raw hourly → clean daily |
| `run_daily.py` | Orchestrates fetch + clean |
| `coverage_report.py` | Checks data coverage, writes `cities.json` |
| `config.py` | Shared paths, constants, helper functions |
| `debloat.py` | Trims the raw file to save disk space |
| `compress.py` | Re-compresses data files |
| `daily.yml` | GitHub Actions workflow for the daily update |

## EDA Notebook

`EDA.ipynb` explores the cleaned data. It covers:

- Dataset overview and missing value audit
- Data availability heatmap by city and month
- PM2.5 distributions, boxplots and health category breakdown (US EPA + WHO guideline)
- Time series with 7-day rolling mean
- Seasonal analysis (smog season Oct–Feb vs rest of year)
- Day-of-week patterns, correlations between cities and variables
- Autocorrelation and day-to-day change (baseline error for forecasting)
- PM2.5 / PM10 ratio trends

Run it after `fetch_365.py` and `run_daily.py` so `data/clean_daily.csv.gz` exists.
