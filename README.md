# ERA5 fire weather analysis

Configurable ERA5 point/regional downloads, processed weather datasets, meteograms, regional weather maps, and topographic context maps. The topography workflow can generate both a regional terrain view and a zoomed view around the meteogram point, with an optional shapefile overlay on the zoomed map. Requires Python 3.10+.

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

`run` executes download, process and plot in sequence. If all entries in `outputs` are `false`, the plotting stage is skipped automatically after the processed data files have been written.

- `mode`: `point`, `maps`, or `both`. Point mode needs no region; maps mode needs no point.
- `start`, `end`: inclusive UTC timestamps on whole hours. Explicit offsets are accepted. A date without a time means midnight, not the whole day.
- `point`: name, latitude and longitude; extraction uses the nearest grid cell and records its coordinates.
- `region`: north, west, south, east in degrees. Longitude uses -180 to 180; split regions crossing the antimeridian.
- `maps.topography`: enable the regional shaded-elevation map (default `true`). First use downloads Copernicus GLO-90 tiles; subsequent plots reuse `raw/topography/`. Set to `false` to skip terrain downloads and rendering.
- `maps.topography_zoom`: enable the point-centred topographic zoom (default `true` when topography is enabled).
- `maps.topography_zoom_radius_km`: radius of the zoom around the meteogram point in kilometres. For example, `20` produces a view extending approximately 20 km in every direction from the point.
- `maps.topography_overlay`: optional shapefile overlay drawn only on the zoomed topography. The overlay highlights the supplied geometry but does not control the zoom extent.
- `maps.every_hours`: interval counted from start. Alternatively `maps.times` supplies exact timestamps and takes precedence.
- `maps.coastlines`, `maps.borders`, `maps.lakes`, `maps.cities`: enable geographic context on regional weather maps and topography maps.
- `maps.city_min_population`, `maps.max_cities`: filter the Natural Earth populated places used for city labels.
- `timezone`: meteogram display timezone; data and map labels remain UTC.
- `outputs.png`, `outputs.pdf`: control whether static figures are written to disk.
- `outputs.interactive`: control creation of the self-contained `maps_interactive.html` viewer. The HTML can be created without writing PNG/PDF files to disk; its images are rendered in memory and embedded in the HTML.
- `output`: path relative to the configuration file.

### Configuration modes and output combinations

The configuration separates **what data are downloaded** (`mode`) from **what presentation products are written** (`outputs`). This makes it possible to use the package for data-only extraction, static figures, interactive HTML, or any combination.

#### `mode: point` — point weather only

Only the point-area ERA5 request is downloaded. Processing extracts the nearest ERA5 grid cell to the requested coordinates and writes `point.nc` and `point.csv`. No regional map data are requested.

A data-only point configuration is:

```yaml
start: "2023-07-24T00:00:00Z"
end: "2023-07-26T23:00:00Z"
mode: point

point:
  name: Palermo
  latitude: 38.12
  longitude: 13.36

timezone: Europe/Rome
output: output/example_point_data_only

outputs:
  png: false
  pdf: false
  interactive: false
```

To create a meteogram from the same point data, enable one or both static formats:

```yaml
outputs:
  png: true
  pdf: false
  interactive: false
```

With `mode: point`, `outputs.interactive` is not used because the interactive product is a regional map viewer.

#### `mode: maps` — regional weather maps only

Only the regional ERA5 request is downloaded and processed to `maps.nc`. A `point` block is not required, and no meteogram is generated.

For regional data only:

```yaml
start: "2023-07-24T00:00:00Z"
end: "2023-07-26T23:00:00Z"
mode: maps

region:
  north: 39.0
  west: 11.0
  south: 36.0
  east: 16.0

timezone: Europe/Rome
output: output/example_maps_data_only

outputs:
  png: false
  pdf: false
  interactive: false

maps:
  every_hours: 1
```

For an interactive regional viewer without standalone PNG/PDF figures:

```yaml
outputs:
  png: false
  pdf: false
  interactive: true

maps:
  every_hours: 1
  coastlines: true
  borders: true
  lakes: true
  cities: true
  topography: true
  topography_zoom: false
  interactive_dpi: 110
  interactive_interval_ms: 900
```

The weather-map frames and topography needed by the HTML are rendered to memory and embedded as base64 images, so no temporary or final PNG files are required on disk.

#### `mode: both` — point + regional weather

This downloads and processes both streams independently. The output includes `point.nc`, `point.csv`, and `maps.nc`. Static figures and/or the interactive viewer can then be selected with `outputs`.

A useful interactive-only configuration is:

```yaml
mode: both

point:
  name: Palermo
  latitude: 38.12
  longitude: 13.36

region:
  north: 39.0
  west: 11.0
  south: 36.0
  east: 16.0

outputs:
  png: false
  pdf: false
  interactive: true

maps:
  every_hours: 1
  topography: true
  topography_zoom: true
  topography_zoom_radius_km: 20
  interactive_meteogram: true
```

This produces the processed point and regional datasets plus one self-contained interactive HTML file, without standalone PNG/PDF figures.

#### Output selection

The three output flags are independent:

| Configuration | Result |
| --- | --- |
| `png: false`, `pdf: false`, `interactive: false` | processed data only; plotting is skipped |
| `png: true`, `pdf: false`, `interactive: false` | PNG static figures |
| `png: false`, `pdf: true`, `interactive: false` | PDF static figures |
| `png: false`, `pdf: false`, `interactive: true` | interactive HTML only |
| `png: true`, `pdf: false`, `interactive: true` | PNG static figures + interactive HTML |
| `png: false`, `pdf: true`, `interactive: true` | PDF static figures + interactive HTML |
| `png: true`, `pdf: true`, `interactive: true` | all static and interactive products |

When all three flags are `false`, `era5-fire run` still performs download and processing, then skips plotting entirely. In this case a `figures/` directory is not created by the plotting stage.

The preferred syntax is the `outputs` block above. The older `formats: [png, pdf]` and `maps.interactive` settings are still accepted for backward compatibility, but new configurations should use `outputs`.

#### Typical example configuration files

The repository can keep separate example YAML files for the most common workflows:

- `example_point_data_only.yaml` — `point.nc` and `point.csv` only;
- `example_meteogram_only.yaml` — point data plus a static meteogram;
- `example_maps_data_only.yaml` — `maps.nc` only;
- `example_maps_interactive_only.yaml` — regional interactive HTML only;
- `example_both_interactive_only.yaml` — point + maps data and self-contained HTML, without standalone figures;
- `example_everything.yaml` — point + maps data, PNG, PDF, and interactive HTML.

### Optional topography shapefile overlay

To highlight an area on the zoomed topography, add a `topography_overlay` block under `maps`:

```yaml
maps:
  topography: true
  topography_zoom: true
  topography_zoom_radius_km: 20

  topography_overlay:
    path: ../data/fire_perimeter.shp
    edgecolor: "#d7191c"
    linewidth: 2.0
    alpha: 1.0
    label: Fire perimeter
```

The overlay is intended as a visual highlight only:

- the regional topography remains unchanged;
- the zoom remains centred on the meteogram point;
- the shapefile geometry does not redefine the zoom extent;
- polygon layers are drawn as boundaries/perimeters, so the terrain remains visible inside the polygon;
- line and point layers can also be displayed;
- the shapefile CRS must be defined; it is reprojected to EPSG:4326 for plotting;
- the `.shp`, `.dbf`, `.shx`, `.prj` and any other required sidecar files must remain together.

The overlay path is resolved relative to the YAML configuration file. The overlay uses GeoPandas, so the environment must include `geopandas` and its normal geospatial dependencies.


Point data are downloaded hourly in a small box; regional data hourly between the first and last map times, to calculate precipitation totals. Requests are split by day and cached by request content. These streams have independent caches. Downloads use temporary files and retries. Delete a cached file to refresh preliminary ERA5T data after final ERA5 becomes available.

## Outputs

- `raw/`: original downloads and JSON request metadata.
- `point.nc`, `point.csv`: temperature/dewpoint (°C), RH (%), wind/gust (m/s), direction (degrees), precipitation (mm), VPD (kPa), and trailing 24-hour precipitation. CSV timestamps include UTC offsets; NetCDF times are UTC.
- `figures/topography.png` (and/or PDF): regional Copernicus GLO-90 elevation with hillshading and the meteogram location.
- `figures/topography_zoom.png` (and/or PDF): topography zoom centred on the meteogram point. If `maps.topography_overlay` is configured, the shapefile is drawn on this zoomed view only.
- `maps.nc`: hourly processed fields between the first and last selected map timestamps.
- `figures/meteogram.png` (and/or PDF): four panels: temperature and dew point; relative humidity on a separate panel; wind speed/gusts with direction arrows; and hourly precipitation bars with cumulative precipitation on the right axis. Relative humidity is shown as a solid line and cumulative precipitation as a grey line. Fixed 18:00–06:00 night shading uses the configured timezone. VPD remains in the data exports but is not plotted.
- `figures/maps.png` (and/or PDF): one combined figure with a row per selected timestamp and columns for temperature, RH, wind and accumulated precipitation. Four shared discrete colourbars apply to every row. Old individual timestamp figures from earlier runs are not removed automatically.
- `figures/maps_interactive.html`: self-contained browser viewer. Regional and zoomed topography maps are shown first when available, followed by the time controls, then a wide point meteogram beside a column of four equally sized weather maps aligned with its equal-height temperature, humidity, wind and precipitation panels. `maps.interactive_map_layout` defaults to `column`; `2x2` and `row` are also available. Narrow screens stack the figures vertically. The time slider updates the weather-map frame and moves the vertical time marker on the meteogram. Clicking or dragging across the meteogram selects the nearest available map timestamp and synchronizes the slider; this also works with touch. Focus the meteogram and use arrow keys to step through frames, or Home/End to jump to the first/last frame. Selecting a time stops playback. In map-only mode there is no meteogram. If a shapefile overlay is configured, it is visible on the zoomed topography in the HTML as well. The embedded images are generated in memory, so `outputs.interactive: true` does not require `outputs.png: true`.

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

Topography uses [Copernicus GLO-90](https://registry.opendata.aws/copernicus-dem/), a digital surface model including vegetation and buildings, resampled for display. It does not change the ERA5 grid or weather values. Terrain tiles require internet access on first use; subsequent runs reuse the local topography cache.

The regional topography uses the configured `region`. The zoomed topography uses the meteogram point and `maps.topography_zoom_radius_km`; longitude extent is adjusted for latitude so the requested radius is approximately symmetric in kilometres. Coastlines, borders, lakes and filtered Natural Earth city labels can be displayed using the same `maps.*` geographic-context options as the weather maps. An optional `maps.topography_overlay` shapefile is reprojected to EPSG:4326 and drawn only on the zoomed view as a highlight. It does not modify the DEM, ERA5 data, or zoom extent.

The generated `maps_interactive.html` remains self-contained: weather frames, meteogram and both topography images are embedded directly in the HTML, so the file can be opened locally in a normal web browser without a web server.
