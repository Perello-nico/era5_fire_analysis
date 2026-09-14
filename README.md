# ERA5 fire weather analysis

Configurable ERA5 downloads, meteograms and regional weather maps. Requires Python 3.10+.

## Setup

With uv installed, run from the project directory:

```bash
uv sync --extra test
```

This creates or updates `.venv` and installs the project and its test dependencies.
Use `uv sync` if you do not need the test dependencies. Run commands with `uv run`
without activating the environment:

```bash
uv run era5-fire plan --config example/example.yaml
uv run era5-fire run --config example/example.yaml
```

Credentials still belong in `~/.cdsapirc`, as described below.

Alternatively, use Python's venv and pip:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
```

Register at the [Climate Data Store](https://cds.climate.copernicus.eu/), accept the terms on the [ERA5 single-level dataset download page](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels?tab=download), and follow the [CDS API setup](https://cds.climate.copernicus.eu/how-to-api). Store your personal access token in `~/.cdsapirc`, outside this repository:

```yaml
url: https://cds.climate.copernicus.eu/api
key: YOUR_PERSONAL_ACCESS_TOKEN
```

## Configure and run

Edit `example/example.yaml` to set dates, location, region and map times. Palermo is only an example. This is also the default configuration when `--config` is omitted (run from the project directory). Its `output: output` setting writes results to `example/output/`.

```bash
# Inspect exact requests without network access or credentials.
era5-fire plan --config example/example.yaml
# Download, process and plot.
era5-fire run --config example/example.yaml
```

Stages can also run separately:

```bash
era5-fire download --config example/example.yaml
era5-fire process --config example/example.yaml
era5-fire plot --config example/example.yaml
```

- `mode`: `point`, `maps`, or `both`. Point mode needs no region; maps mode needs no point.
- `start`, `end`: inclusive UTC timestamps on whole hours. Explicit offsets are accepted. A date without a time means midnight, not the whole day.
- `point`: name, latitude and longitude; extraction uses the nearest grid cell and records its coordinates.
- `region`: north, west, south, east in degrees. Longitude uses -180 to 180; split regions crossing the antimeridian.
- `maps.topography`: enable the separate shaded elevation panel (default `true`). First use downloads Copernicus GLO-90 tiles; subsequent plots reuse `raw/topography/`. Set to `false` to skip terrain downloads and rendering.
- `maps.every_hours`: interval counted from start. Alternatively `maps.times` supplies exact timestamps and takes precedence.
- `timezone`: meteogram display timezone; data and map labels remain UTC.
- `formats`: PNG and/or PDF.
- `output`: path relative to the configuration file.

Point data are downloaded hourly in a small box; regional data hourly between the first and last map times, to calculate precipitation totals. Requests are split by day and cached by request content. These streams have independent caches. Downloads use temporary files and retries. Delete a cached file to refresh preliminary ERA5T data after final ERA5 becomes available.

## Outputs

- `raw/`: original downloads and JSON request metadata.
- `point.nc`, `point.csv`: temperature/dewpoint (°C), RH (%), wind/gust (m/s), direction (degrees), precipitation (mm), VPD (kPa), and trailing 24-hour precipitation. CSV timestamps include UTC offsets; NetCDF times are UTC.
- `figures/topography.png` (and/or PDF): elevation in metres with hillshading and the meteogram location. Also embedded as a static panel below the weather maps in `maps_interactive.html`; the existing meteogram → slider → maps order is preserved.
- `maps.nc`: hourly processed fields between the first and last selected map timestamps.
- `figures/meteogram.png` (and/or PDF): three panels styled after `~/Codes/meteogram`: combined temperature/dewpoint and dotted RH on a secondary axis; wind speed/gusts with direction arrows; hourly precipitation bars with a cumulative precipitation line on the right axis (mm), summed from the first available hour. Fixed 18:00–06:00 night shading uses the configured timezone. VPD remains in the data exports but is not plotted.
- `figures/maps.png` (and/or PDF): one combined figure with a row per selected timestamp and columns for temperature, RH, wind and accumulated precipitation. Four shared discrete colourbars apply to every row. Old individual timestamp figures from earlier runs are not removed automatically.

Map palettes approximate the supplied reference screenshots; explicit colours and boundaries are in `era5_fire/plotting.py`. Temperature bands span −48 to 56°C every 4°C. RH boundaries are 5, 10, 20, …, 100%, with brown below 5%. Temperature and RH use their end colours outside these ranges. Wind shading uses km/h: 0–10 is transparent, 10–20 pale yellow, then 10 km/h bands from yellow through green to dark blue; values at or above 90 use the darkest blue. Wind barbs also use km/h (half barb 5, full barb 10, pennant 50), as labelled on the figure. Meteogram wind arrows point in the direction of motion; exported wind values remain in m/s.

Precipitation boundaries are 0.5, 2, 4, 10, 25, 50, 100 and 250 mm, using the supplied cyan–blue–purple–magenta–orange–red palette. Values below 0.5 mm are transparent; values above 250 mm remain red. Older sparse `maps.nc` files require rerunning `download` and `process` to obtain the intervening hours. Regional downloads are larger because they now include every hour.

To regenerate figures from processed data containing those hourly values:

```bash
uv run era5-fire plot --config example/example.yaml
```

Cartopy may download Natural Earth coastlines on first use. Set `maps.coastlines: false` to avoid this dependency. Processing loads each stream into memory; split large domains or long periods into separate configurations.

## Scientific conventions

ERA5 has a 0.25° CDS grid and approximately 31 km native atmospheric resolution. Grid values do not resolve local slopes or fine terrain effects.

Relative humidity and VPD use a Magnus approximation over liquid water, including below freezing. RH is bounded to 0–100%; VPD is nonnegative. Wind direction uses the meteorological **from** convention and is undefined for speeds below 0.1 m/s.

For this hourly ERA5 CDS product, precipitation is water equivalent in the hour **ending** at its timestamp, including snow. Metres are converted to millimetres without differencing successive hours. Gusts are maxima since previous post-processing, over the preceding hour. Map precipitation is cumulative from the first selected map's available hour through the current map time, including the hour ending at the first map timestamp. The first map shows its preceding hour; subsequent maps retain that amount and add every following hour. Each precipitation panel labels its interval in UTC; totals include snow water equivalent. Gusts remain hourly maxima. Trailing 24-hour precipitation is missing until 24 samples exist; request an earlier start for antecedent conditions. Formal Fire Weather Index calculations are not implemented.

The reader handles ZIP archives with separate instantaneous, accumulated and gust NetCDF files, and merges ERA5/ERA5T `expver` values preferring final ERA5. Missing values or unexpected timestamps stop processing rather than silently filling gaps.

References: [ERA5 documentation](https://confluence.ecmwf.int/spaces/CKB/pages/76414402/ERA5+data+documentation) and [dataset overview](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels?tab=overview).

## Tests

Run from the project directory. With uv, include the test dependencies:

```bash
uv run --extra test pytest -q
```

Or with the pip environment activated:

```bash
pytest -q
```

Validate the relocated example and inspect its download requests without downloading data or needing CDS credentials:

```bash
uv run era5-fire plan --config example/example.yaml
```

The automated tests create temporary configurations and outputs; they do not download or modify the example data. Synthetic tests cover humidity, cardinal wind directions, precipitation timing, requests across month boundaries, split NetCDF archives, CSV/NetCDF exports and map/meteogram rendering without coastline downloads. No CDS credentials are needed for tests.

Topography uses [Copernicus GLO-90](https://registry.opendata.aws/copernicus-dem/), a digital surface model including vegetation and buildings, resampled for display. It does not change the ERA5 grid or weather values. Terrain tiles require internet access on first use; the generated HTML remains self-contained.
