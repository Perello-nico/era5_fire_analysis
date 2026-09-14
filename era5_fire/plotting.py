"""Static meteograms, fire-weather maps, and a self-contained HTML map viewer."""
import base64
import io
import json
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap
import numpy as np
import pandas as pd

# Discrete colours approximated from the user-provided reference images.
# End colours extend to values outside the displayed temperature/RH range.
PALETTES = {
    "precipitation_accumulation": (
        [0.5, 2, 4, 10, 25, 50, 100, 250],
        ["#60f5f5", "#347ef5", "#1000f0", "#b51ff0",
         "#f000f0", "#ff801a", "#e51b0a"],
    ),
    "wind_speed": (
        list(range(0, 101, 10)),
        ["#ffffff00", "#fff9b0", "#ffff4d", "#a2e529", "#65d421",
         "#32bc42", "#32a480", "#297c8e", "#183a78", "#10005b"],
    ),
    "temperature": (
        list(range(-48, 57, 4)),
        ["#10005b", "#18008b", "#2100ae", "#2900d5", "#3200ff",
         "#394dff", "#3b82ff", "#35baff", "#31eddf", "#45ff9b",
         "#68ff47", "#99ff32", "#c9ff32", "#eeff32", "#ffff32",
         "#ffe32b", "#ffc124", "#ff9d1c", "#ff7214", "#ff460c",
         "#fa2108", "#e91013", "#c90a42", "#b70c83", "#d51cce", "#ff2bef"],
    ),
    "relative_humidity": (
        [5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
        ["#a65324", "#df302d", "#f34421", "#f76c18", "#fa9420",
         "#ffff4d", "#e4ff55", "#c3ff59", "#9aff63", "#63ee99"],
    ),
}


def palette(variable):
    boundaries, colors = PALETTES[variable]
    cmap = ListedColormap(colors, name=f"fire_{variable}")
    cmap = cmap.with_extremes(under=(0, 0, 0, 0) if variable == "precipitation_accumulation" else colors[0], over=colors[-1], bad=(0, 0, 0, 0))
    return cmap, BoundaryNorm(boundaries, cmap.N)


def meteogram(ds, c, highlight_time=None):
    """Three panels: T/Td/RH, wind/gust/direction, and precipitation.

    If ``highlight_time`` is supplied, draw a vertical line at that valid time.
    The interactive HTML viewer uses the same axes geometry to overlay a
    browser-side moving line without re-rendering the meteogram for every step.
    """
    times = pd.DatetimeIndex(ds.time.values)
    if times.tz is None:
        times = times.tz_localize("UTC")
    else:
        times = times.tz_convert("UTC")
    times = times.tz_convert(c["timezone"])

    tz = ZoneInfo(c["timezone"])
    fig, axes = plt.subplots(3, 1, figsize=(13, 9), sharex=True,
                             gridspec_kw={"height_ratios": [1.2, 1, .75]})
    fig.subplots_adjust(left=.08, right=.92, bottom=.1, top=.8, hspace=.35)

    rh = axes[0].twinx()
    axes[0].plot(times, ds.temperature, color="#ff3b30", lw=2, label="Temperature")
    axes[0].plot(times, ds.dewpoint, color="#9b6bd6", lw=2, label="Dew point")
    rh.plot(times, ds.relative_humidity, color="#0c53e0", lw=2, ls=":",
            label="Relative humidity")
    rh.set(ylabel="%", ylim=(0, 100))
    axes[0].set(ylabel="°C", title="Temperature and relative humidity")
    axes[0].margins(y=.15)

    speed = ds.wind_speed.values * 3.6
    gust = ds.wind_gust.values * 3.6
    axes[1].plot(times, speed, color="#2ecc71", lw=2, label="Wind speed")
    axes[1].plot(times, gust, color="#198754", lw=1.5, ls="--",
                 label="Hourly maximum gust")
    maximum = max(float(np.nanmax(speed)), float(np.nanmax(gust)), 1)

    stride = max(1, int(np.ceil(len(times) / 48)))
    direction = np.deg2rad(ds.wind_direction.values[::stride])
    axes[1].quiver(
        mdates.date2num(times[::stride]),
        np.full(len(direction), maximum * 1.12),
        -np.sin(direction), -np.cos(direction),
        angles="uv", scale_units="inches", scale=7,
        width=.002, pivot="middle", color="#1b1e1b",
    )
    axes[1].set(
        ylabel="km/h",
        ylim=(0, maximum * 1.28),
        title="Wind - arrows show direction of motion",
    )

    axes[2].bar(
        times, ds.precipitation,
        width=-1/24, align="edge", color="#4682b4",
        label="Hourly precipitation",
    )
    axes[2].set(
        ylabel="Hourly (mm)",
        title="Hourly precipitation and accumulation from the first hour",
        ylim=(0, None),
    )
    accumulated_rain = axes[2].twinx()
    accumulated_rain.plot(
        times, ds.precipitation.cumsum("time", skipna=False),
        color="#b51ff0", lw=2, label="Accumulated precipitation",
    )
    accumulated_rain.set(ylabel="Accumulated (mm)", ylim=(0, None))
    accumulated_rain.tick_params(axis="y", colors="#b51ff0")
    accumulated_rain.yaxis.label.set_color("#b51ff0")

    days = pd.date_range(
        times[0].normalize() - pd.DateOffset(days=1),
        times[-1].normalize() + pd.DateOffset(days=1),
        freq="D",
    )
    for ax in axes:
        ax.set_facecolor("white")
        ax.grid(color="#dce1e6", lw=.7)
        ax.set_axisbelow(True)
        for spine in ax.spines.values():
            spine.set_color("#444444")
        for day in days:
            night_start = day + pd.DateOffset(hours=18)
            night_end = day + pd.DateOffset(days=1, hours=6)
            ax.axvspan(night_start, night_end, color="#95a0a4", alpha=.1, lw=0)
            ax.axvline(day, color="#111111", alpha=.2, ls=":", lw=1.8)

    if highlight_time is not None:
        marker_time = pd.Timestamp(highlight_time)
        if marker_time.tzinfo is None:
            marker_time = marker_time.tz_localize("UTC")
        else:
            marker_time = marker_time.tz_convert("UTC")
        marker_time = marker_time.tz_convert(c["timezone"])
        for ax in axes:
            ax.axvline(marker_time, color="black", lw=1.7, zorder=25)

    axes[-1].set_xlim(
        times[0] - pd.Timedelta(hours=1),
        times[-1] + pd.Timedelta(minutes=30),
    )
    axes[-1].xaxis.set_major_formatter(
        mdates.DateFormatter("%d %b\n%H:%M %Z", tz=tz)
    )
    axes[-1].set_xlabel(f"Time ({c['timezone']})")

    handles, labels = [], []
    for ax in [axes[0], rh, axes[1], axes[2], accumulated_rain]:
        h, l = ax.get_legend_handles_labels()
        handles.extend(h)
        labels.extend(l)
    fig.legend(
        handles, labels,
        loc="upper center", bbox_to_anchor=(.5, .9),
        ncol=3, frameon=False,
    )

    p = c["point"]
    fig.suptitle(
        f"{p.get('name', 'Location')} - ERA5\n"
        f"Requested {p['latitude']:.3f}, {p['longitude']:.3f}; "
        f"grid {float(ds.latitude):.3f}, {float(ds.longitude):.3f}",
        y=.98,
    )
    return fig


def _map_reference_time(ds, c):
    """Return the map reference time, if supplied by config or dataset metadata."""
    value = c.get("reference_time")
    if value is None:
        for key in ("reference_time", "forecast_reference_time", "analysis_time"):
            if key in ds.attrs:
                value = ds.attrs[key]
                break
    if value is None:
        return None

    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts


def _load_map_cities(region, maps_config):
    """Load a small set of Natural Earth cities inside the plotted region."""
    if not maps_config.get("cities", True):
        return []

    import cartopy.io.shapereader as shpreader

    shp = shpreader.natural_earth(
        resolution="10m",
        category="cultural",
        name="populated_places",
    )

    west, east = region["west"], region["east"]
    south, north = region["south"], region["north"]
    min_population = maps_config.get("city_min_population", 100_000)
    max_cities = maps_config.get("max_cities", 8)

    cities = []
    for record in shpreader.Reader(shp).records():
        geom = record.geometry
        if geom is None or geom.is_empty:
            continue
        lon, lat = geom.x, geom.y
        if not (west <= lon <= east and south <= lat <= north):
            continue

        attrs = record.attributes
        population = attrs.get("POP_MAX") or 0
        try:
            population = float(population)
        except (TypeError, ValueError):
            population = 0

        if population < min_population:
            continue

        name = attrs.get("NAME") or attrs.get("NAMEPAR") or attrs.get("ADM0NAME")
        if name:
            cities.append((population, str(name), lon, lat))

    cities.sort(reverse=True, key=lambda item: item[0])
    return cities[:max_cities]


def map_accumulations(ds, c):
    """Sum hourly precipitation from the first map's hour through each map.

    The first frame uses its preceding hour. Reject incomplete windows,
    including older sparse maps.nc files, instead of understating totals.
    """
    import xarray as xr

    times = pd.DatetimeIndex(c.get("map_times", ds.time.values))
    if times.tz is not None:
        times = times.tz_convert("UTC").tz_localize(None)
    if times.empty or times.has_duplicates or not times.is_monotonic_increasing:
        raise ValueError("Map timestamps must be nonempty, unique and increasing")
    actual = pd.DatetimeIndex(ds.time.values)
    totals, starts = [], []
    start = times[0] - pd.Timedelta(hours=1)
    for end in times:
        hours = pd.date_range(start + pd.Timedelta(hours=1), end, freq="h")
        if actual.has_duplicates or not hours.isin(actual).all():
            raise ValueError("Rain accumulation requires every intervening hour; "
                             "rerun download and process to refresh maps.nc")
        total = ds.precipitation.sel(time=hours).sum("time", skipna=False)
        totals.append(total)
        starts.append(start.to_datetime64())
    result = xr.concat(totals, pd.Index(times, name="time"))
    result.attrs = {"units": "mm", "description": "Cumulative precipitation including the first map's preceding hour"}
    return result.assign_coords(accumulation_start=("time", starts))


def maps(ds, c, times=None, cities=None):
    """One row per timestamp, four columns, with shared discrete legends."""
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature

    projection = ccrs.PlateCarree()
    accumulation = map_accumulations(ds, c)
    ds = ds.assign(precipitation_accumulation=accumulation)

    # Static maps use all configured map times. The interactive viewer passes
    # one time at a time so it can render one compact frame per slider step.
    selected_times = c.get("map_times") if times is None else pd.DatetimeIndex(times)
    if selected_times is not None:
        selected_times = pd.DatetimeIndex(selected_times)
        if selected_times.tz is not None:
            selected_times = selected_times.tz_convert("UTC").tz_localize(None)
        ds = ds.sel(time=selected_times.values)

    count = ds.sizes["time"]
    fig = plt.figure(figsize=(21, 3.8 * count + 1.5))
    grid = fig.add_gridspec(
        count + 1, 4,
        height_ratios=[1] * count + [.06],
        left=.10, right=.98,
        top=.88 if count == 1 else .92,
        bottom=.08 if count == 1 else .045,
        wspace=.17, hspace=.22,
    )

    axes = np.array([
        [fig.add_subplot(grid[row, col], projection=projection) for col in range(4)]
        for row in range(count)
    ])

    fields = [
        ("temperature", "2 m temperature (°C)"),
        ("relative_humidity", "2 m relative humidity (%)"),
        ("wind_speed", "10 m wind speed (km/h)"),
        ("precipitation_accumulation", "Accumulated precipitation (mm)"),
    ]

    r = c["region"]
    maps_config = c.get("maps", {})
    if cities is None:
        cities = _load_map_cities(r, maps_config)

    # Point corresponding to the meteogram. If exact grid coordinates are
    # supplied they are preferred; otherwise the requested coordinates are used.
    p = c.get("point")
    if p is not None:
        point_lon = p.get("grid_longitude", p["longitude"])
        point_lat = p.get("grid_latitude", p["latitude"])

    # Higher-resolution geographic features.
    admin1 = cfeature.NaturalEarthFeature(
        category="cultural",
        name="admin_1_states_provinces_lines",
        scale="10m",
        facecolor="none",
    )

    artists = []
    for row, t in enumerate(ds.time.values):
        frame = ds.sel(time=t)

        for col, (name, label) in enumerate(fields):
            ax = axes[row, col]
            cmap, norm = palette(name)
            values = frame[name].transpose("latitude", "longitude")
            if name == "wind_speed":
                values = values * 3.6

            art = ax.pcolormesh(
                frame.longitude, frame.latitude, values,
                transform=projection, shading="auto", cmap=cmap, norm=norm,
            )

            if name == "precipitation_accumulation":
                start = pd.Timestamp(accumulation.accumulation_start.sel(time=t).values)
                ax.text(.5, 1.02,
                        f"{start:%d %b %H:%M} – {pd.Timestamp(t):%d %b %H:%M} UTC",
                        transform=ax.transAxes, ha="center", fontsize=8)

            if row == 0:
                artists.append(art)
                position = ax.get_position()
                fig.text(
                    (position.x0 + position.x1) / 2,
                    position.y1 + .045,
                    label,
                    ha="center", va="bottom", fontsize=12,
                )

            ax.set_extent(
                [r["west"], r["east"], r["south"], r["north"]],
                crs=projection,
            )

            # Better coastlines and geographic context.
            if maps_config.get("coastlines", True):
                ax.coastlines(resolution="10m", linewidth=.8, color="black", zorder=4)
            if maps_config.get("borders", True):
                ax.add_feature(cfeature.BORDERS.with_scale("10m"), linewidth=.55,
                               edgecolor="black", zorder=4)
            if maps_config.get("admin1", False):
                ax.add_feature(admin1, linewidth=.35, edgecolor="0.25", zorder=4)
            if maps_config.get("lakes", True):
                ax.add_feature(cfeature.LAKES.with_scale("10m"), facecolor="none",
                               edgecolor="0.3", linewidth=.45, zorder=4)

            # location inspected in the meteogram.
            if p is not None:
                ax.plot(
                    point_lon, point_lat,
                    marker="X", markersize=5.5,
                    markerfacecolor="black", markeredgecolor="white",
                    markeredgewidth=.8,
                    transform=projection, zorder=10,
                )

            # Optional city labels, filtered to avoid overcrowding.
            for _, city_name, city_lon, city_lat in cities:
                ax.plot(city_lon, city_lat, marker="o", markersize=2.0,
                        color="black", transform=projection, zorder=8)
                ax.text(
                    city_lon, city_lat, f"  {city_name}",
                    transform=projection,
                    fontsize=7, color="black",
                    ha="left", va="center", zorder=8,
                    bbox={"facecolor": "white", "alpha": .55,
                          "edgecolor": "none", "pad": .5},
                )

            gl = ax.gridlines(draw_labels=True, alpha=.25, linewidth=.6)
            gl.top_labels = gl.right_labels = False
            gl.xlabel_style = gl.ylabel_style = {"size": 8}

            # This is the VALID time of each map row.
            if col == 0:
                position = ax.get_position()
                fig.text(
                    .025,
                    (position.y0 + position.y1) / 2,
                    f"Valid time\n{pd.Timestamp(t):%d %b %Y}\n{pd.Timestamp(t):%H:%M} UTC",
                    rotation=90,
                    ha="center", va="center", fontsize=10,
                )

        stride = max(
            1,
            int(np.ceil(max(frame.sizes["latitude"], frame.sizes["longitude"]) / 15)),
        )
        wind = frame.isel(
            latitude=slice(None, None, stride),
            longitude=slice(None, None, stride),
        )
        lon, lat = np.meshgrid(wind.longitude, wind.latitude)

        # Explicit km/h increments: half barb=5, full barb=10, pennant=50.
        axes[row, 2].barbs(
            lon, lat,
            wind.u10.transpose("latitude", "longitude").values * 3.6,
            wind.v10.transpose("latitude", "longitude").values * 3.6,
            transform=projection,
            length=4.5, linewidth=.5,
            barb_increments={"half": 5, "full": 10, "flag": 50},
            flip_barb=lat < 0,
            zorder=7,
        )

    for col, (name, label) in enumerate(fields):
        bounds = PALETTES[name][0]
        ticks = bounds[::2] if name == "temperature" else bounds
        cb = fig.colorbar(
            artists[col],
            cax=fig.add_subplot(grid[-1, col]),
            orientation="horizontal",
            label=label,
            ticks=ticks,
            spacing="uniform",
            drawedges=True,
        )
        cb.ax.tick_params(labelsize=7)

    reference_time = _map_reference_time(ds, c)
    title = "ERA5 weather"
    if reference_time is not None:
        title += f"\nReference time: {reference_time:%d %b %Y %H:%M UTC}"
    fig.suptitle(title, fontsize=13)

    return fig


def interactive_maps(ds, c, output_path):
    """Create a self-contained HTML viewer synchronized with the meteogram.

    The map sequence is rendered with the same Matplotlib/Cartopy ``maps``
    function used for static output. A single meteogram PNG is embedded above
    the maps. JavaScript moves a vertical line across that meteogram whenever
    the map slider changes. No web server is required.
    """
    from pathlib import Path

    maps_config = c.get("maps", {})
    dpi = maps_config.get("interactive_dpi", 110)
    meteogram_dpi = maps_config.get("interactive_meteogram_dpi", dpi)
    interval_ms = maps_config.get("interactive_interval_ms", 900)
    include_meteogram = maps_config.get("interactive_meteogram", True)

    if "map_times" in c:
        frame_times = pd.DatetimeIndex(c["map_times"])
    else:
        frame_times = pd.DatetimeIndex(ds.time.values)

    if frame_times.tz is None:
        frame_times = frame_times.tz_localize("UTC")
    else:
        frame_times = frame_times.tz_convert("UTC")

    if len(frame_times) == 0:
        raise ValueError("Cannot create interactive maps without map timestamps")

    cities = _load_map_cities(c["region"], maps_config)
    display_tz = ZoneInfo(c.get("timezone", "UTC"))

    frames = []
    total = len(frame_times)
    print(f"Generating {total} interactive map frames...")

    for i, t in enumerate(frame_times, start=1):
        print(f"  Interactive frame {i}/{total}: {t:%Y-%m-%d %H:%M} UTC")
        fig = maps(ds, c, times=[t], cities=cities)
        buffer = io.BytesIO()
        try:
            fig.savefig(
                buffer,
                format="png",
                dpi=dpi,
                bbox_inches="tight",
                facecolor="white",
            )
        finally:
            plt.close(fig)

        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        local_t = t.tz_convert(display_tz)
        frames.append({
            "src": f"data:image/png;base64,{encoded}",
            "utc": t.strftime("%d %b %Y %H:%M UTC"),
            "local": local_t.strftime("%d %b %Y %H:%M %Z"),
            "timestamp_ms": int(t.timestamp() * 1000),
        })

    meteogram_src = None
    meteogram_axis_start_ms = None
    meteogram_axis_end_ms = None

    if include_meteogram and c.get("point") is not None:
        point_path = Path(c["output"]) / "point.nc"
        if point_path.exists():
            import xarray as xr

            with xr.open_dataset(point_path) as source:
                point_ds = source.load()

            point_times = pd.DatetimeIndex(point_ds.time.values)
            if point_times.tz is None:
                point_times = point_times.tz_localize("UTC")
            else:
                point_times = point_times.tz_convert("UTC")

            axis_start = point_times[0] - pd.Timedelta(hours=1)
            axis_end = point_times[-1] + pd.Timedelta(minutes=30)
            meteogram_axis_start_ms = int(axis_start.timestamp() * 1000)
            meteogram_axis_end_ms = int(axis_end.timestamp() * 1000)

            fig = meteogram(point_ds, c)
            buffer = io.BytesIO()
            try:
                fig.savefig(
                    buffer,
                    format="png",
                    dpi=meteogram_dpi,
                    bbox_inches=None,
                    facecolor="white",
                )
            finally:
                plt.close(fig)

            meteogram_src = (
                "data:image/png;base64," +
                base64.b64encode(buffer.getvalue()).decode("ascii")
            )
        else:
            print(
                "Interactive meteogram skipped: point.nc was not found at "
                f"{point_path}"
            )

    point = c.get("point", {})
    location_name = point.get("name", "ERA5 weather")

    frames_json = json.dumps(
        frames, ensure_ascii=True, separators=(",", ":")
    ).replace("</", "<\\/")
    title_json = json.dumps(str(location_name), ensure_ascii=True).replace("</", "<\\/")
    meteogram_json = json.dumps(meteogram_src, ensure_ascii=True)
    axis_start_json = json.dumps(meteogram_axis_start_ms)
    axis_end_json = json.dumps(meteogram_axis_end_ms)

    document = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ERA5 interactive fire-weather maps</title>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: Canvas;
    color: CanvasText;
  }
  main {
    width: min(1500px, 100%);
    margin: 0 auto;
    padding: 20px;
  }
  h1 { margin: 0 0 4px; font-size: clamp(1.25rem, 3vw, 1.9rem); }
  h2 { margin: 0 0 10px; font-size: 1.05rem; }
  .panel {
    border: 1px solid color-mix(in srgb, CanvasText 18%, transparent);
    border-radius: 10px;
    overflow: hidden;
    background: Canvas;
    margin-bottom: 14px;
  }
  .panel-heading { padding: 12px 16px 0; }
  .map-wrap {
    min-height: 180px;
    display: grid;
    place-items: center;
    background: white;
  }
  #map-image { display: block; width: 100%; height: auto; }
  .meteogram-wrap {
    position: relative;
    width: min(1050px, 100%);
    margin: 0 auto;
    background: white;
    overflow: hidden;
  }
  #meteogram-image { display: block; width: 100%; height: auto; }
  #meteogram-line {
    position: absolute;
    top: 20%;
    bottom: 10%;
    width: 0;
    border-left: 2px solid black;
    pointer-events: none;
    z-index: 5;
  }
  #meteogram-line::before {
    content: "";
    position: absolute;
    top: -4px;
    left: -4px;
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: black;
  }
  .controls { padding: 14px 16px 16px; }
  .time-row {
    display: flex;
    flex-wrap: wrap;
    gap: 8px 18px;
    align-items: baseline;
    justify-content: space-between;
    margin-bottom: 10px;
  }
  #valid-time { font-weight: 700; font-size: 1.05rem; }
  #local-time, #counter { color: GrayText; font-size: .92rem; }
  input[type="range"] { width: 100%; margin: 6px 0 14px; }
  .buttons { display: flex; gap: 8px; flex-wrap: wrap; }
  button {
    min-height: 40px;
    padding: 8px 14px;
    border-radius: 7px;
    border: 1px solid color-mix(in srgb, CanvasText 25%, transparent);
    background: ButtonFace;
    color: ButtonText;
    cursor: pointer;
    font: inherit;
  }
  button:focus-visible, input:focus-visible {
    outline: 2px solid Highlight;
    outline-offset: 2px;
  }
  .hint { margin-top: 10px; color: GrayText; font-size: .85rem; }
  .unavailable { padding: 16px; color: GrayText; }
</style>
</head>
<body>
<main>
  <h1 id="page-title">ERA5 weather maps</h1>

  <section id="meteogram-panel" class="panel">
    <div class="panel-heading"><h2>Point meteogram</h2></div>
    <div id="meteogram-content"></div>
  </section>

  <section class="panel" aria-label="Interactive ERA5 map viewer">
    <div class="panel-heading"><h2>Spatial fields</h2></div>
    <div class="map-wrap">
      <img id="map-image" alt="ERA5 temperature, relative humidity and wind maps">
    </div>
    <div class="controls">
      <div class="time-row">
        <div>
          <div id="valid-time" aria-live="polite"></div>
          <div id="local-time"></div>
        </div>
        <div id="counter"></div>
      </div>

      <label for="time-slider">Valid time</label>
      <input id="time-slider" type="range" min="0" value="0" step="1">

      <div class="buttons">
        <button id="previous" type="button">Previous</button>
        <button id="play" type="button">Play</button>
        <button id="next" type="button">Next</button>
      </div>
      <div class="hint">
        The vertical line in the meteogram follows the valid time selected for the maps.
      </div>
    </div>
  </section>
</main>
<script>
const frames = __FRAMES__;
const locationName = __TITLE__;
const intervalMs = __INTERVAL__;
const meteogramSrc = __METEOGRAM__;
const meteogramAxisStart = __AXIS_START__;
const meteogramAxisEnd = __AXIS_END__;

const image = document.getElementById("map-image");
const slider = document.getElementById("time-slider");
const validTime = document.getElementById("valid-time");
const localTime = document.getElementById("local-time");
const counter = document.getElementById("counter");
const previous = document.getElementById("previous");
const next = document.getElementById("next");
const play = document.getElementById("play");
const meteogramContent = document.getElementById("meteogram-content");

const pageTitle = document.getElementById("page-title");
pageTitle.textContent = locationName + " - ERA5 weather";
slider.max = String(Math.max(0, frames.length - 1));

let meteogramLine = null;
if (meteogramSrc !== null && meteogramAxisStart !== null && meteogramAxisEnd !== null) {
  const wrap = document.createElement("div");
  wrap.className = "meteogram-wrap";

  const metImage = document.createElement("img");
  metImage.id = "meteogram-image";
  metImage.alt = "ERA5 point meteogram";
  metImage.src = meteogramSrc;

  meteogramLine = document.createElement("div");
  meteogramLine.id = "meteogram-line";
  meteogramLine.setAttribute("aria-hidden", "true");

  wrap.appendChild(metImage);
  wrap.appendChild(meteogramLine);
  meteogramContent.appendChild(wrap);
} else {
  const note = document.createElement("div");
  note.className = "unavailable";
  note.textContent = "Point meteogram unavailable. Generate point.nc with mode: both or mode: point.";
  meteogramContent.appendChild(note);
}

let index = 0;
let timer = null;

function moveMeteogramLine(timestampMs) {
  if (meteogramLine === null) return;
  const span = meteogramAxisEnd - meteogramAxisStart;
  if (!(span > 0)) return;

  let fraction = (timestampMs - meteogramAxisStart) / span;
  fraction = Math.max(0, Math.min(1, fraction));

  const leftPercent = 8 + fraction * 84;
  meteogramLine.style.left = leftPercent.toFixed(5) + "%";
}

function showFrame(newIndex) {
  index = Math.max(0, Math.min(frames.length - 1, Number(newIndex)));
  const frame = frames[index];
  image.src = frame.src;
  image.alt = "ERA5 weather maps valid " + frame.utc;
  validTime.textContent = "Valid time: " + frame.utc;
  localTime.textContent = "Local time: " + frame.local;
  counter.textContent = (index + 1) + " / " + frames.length;
  slider.value = String(index);
  moveMeteogramLine(frame.timestamp_ms);
}

function stopPlayback() {
  if (timer !== null) {
    clearInterval(timer);
    timer = null;
  }
  play.textContent = "Play";
}

slider.addEventListener("input", () => {
  stopPlayback();
  showFrame(slider.value);
});

previous.addEventListener("click", () => {
  stopPlayback();
  showFrame(index > 0 ? index - 1 : frames.length - 1);
});

next.addEventListener("click", () => {
  stopPlayback();
  showFrame(index < frames.length - 1 ? index + 1 : 0);
});

play.addEventListener("click", () => {
  if (timer !== null) {
    stopPlayback();
    return;
  }
  play.textContent = "Pause";
  timer = setInterval(() => {
    showFrame(index < frames.length - 1 ? index + 1 : 0);
  }, intervalMs);
});

showFrame(0);
</script>
</body>
</html>
"""

    document = (document
                .replace("__FRAMES__", frames_json)
                .replace("__TITLE__", title_json)
                .replace("__INTERVAL__", str(interval_ms))
                .replace("__METEOGRAM__", meteogram_json)
                .replace("__AXIS_START__", axis_start_json)
                .replace("__AXIS_END__", axis_end_json))

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")
    print(f"Interactive maps saved: {path}")
    return path
