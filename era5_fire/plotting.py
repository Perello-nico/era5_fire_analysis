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


def meteogram(ds, c, highlight_time=None, *, aligned_maps=False):
    """Four panels: T/Td, RH, wind/gust/direction, and precipitation.

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

    # Equal-height panels keep each variable aligned with its weather map.
    fig, axes = plt.subplots(
        4, 1,
        figsize=(13, 13.5 if aligned_maps else 9),
        sharex=True,
        gridspec_kw={"height_ratios": [1, 1, 1, 1]},
    )
    fig.subplots_adjust(
        left=.08, right=.92, bottom=.18, top=.90, hspace=.30
    )

    # 1) Temperature and dew point.
    axes[0].plot(
        times, ds.temperature,
        color="#ff3b30", lw=2, label="Temperature",
    )
    axes[0].plot(
        times, ds.dewpoint,
        color="#9b6bd6", lw=2, label="Dew point",
    )
    axes[0].set(
        ylabel="°C",
        title="Temperature and dew point",
    )
    axes[0].margins(y=.15)

    # 2) Relative humidity on its own panel.
    axes[1].plot(
        times, ds.relative_humidity,
        color="#0c53e0", lw=2, ls="-",
        label="Relative humidity",
    )
    axes[1].set(
        ylabel="%",
        ylim=(0, 100),
        title="Relative humidity",
    )

    # 3) Wind.
    speed = ds.wind_speed.values * 3.6
    gust = ds.wind_gust.values * 3.6
    axes[2].plot(
        times, speed,
        color="#2ecc71", lw=2, label="Wind speed",
    )
    axes[2].plot(
        times, gust,
        color="#198754", lw=1.5, ls="--",
        label="Hourly maximum gust",
    )
    maximum = max(float(np.nanmax(speed)), float(np.nanmax(gust)), 1)

    stride = max(1, int(np.ceil(len(times) / 48)))
    direction = np.deg2rad(ds.wind_direction.values[::stride])
    axes[2].quiver(
        mdates.date2num(times[::stride]),
        np.full(len(direction), maximum * 1.12),
        -np.sin(direction), -np.cos(direction),
        angles="uv", scale_units="inches", scale=7,
        width=.002, pivot="middle", color="#1b1e1b",
    )
    axes[2].set(
        ylabel="km/h",
        ylim=(0, maximum * 1.28),
        title="Wind - arrows show direction of motion",
    )

    # 4) Hourly and accumulated precipitation.
    axes[3].bar(
        times, ds.precipitation,
        width=-1/24, align="edge", color="#4682b4",
        label="Hourly precipitation",
    )
    axes[3].set(
        ylabel="Hourly (mm)",
        title="Hourly precipitation and accumulation from the first hour",
        ylim=(0, None),
    )

    accumulated_rain = axes[3].twinx()
    accumulated_rain.plot(
        times,
        ds.precipitation.cumsum("time", skipna=False),
        color="#808080", lw=2,
        label="Accumulated precipitation",
    )
    accumulated_rain.set(
        ylabel="Accumulated (mm)",
        ylim=(0, None),
    )

    # Fixed 18:00-06:00 night bands in the configured display timezone.
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
            ax.axvspan(
                night_start, night_end,
                color="#95a0a4", alpha=.1, lw=0,
            )
            ax.axvline(
                day,
                color="#111111", alpha=.2, ls=":", lw=1.8,
            )

    if highlight_time is not None:
        marker_time = pd.Timestamp(highlight_time)
        if marker_time.tzinfo is None:
            marker_time = marker_time.tz_localize("UTC")
        else:
            marker_time = marker_time.tz_convert("UTC")
        marker_time = marker_time.tz_convert(c["timezone"])

        for ax in axes:
            ax.axvline(
                marker_time,
                color="black", lw=1.7, zorder=25,
            )

    axes[-1].set_xlim(
        times[0] - pd.Timedelta(hours=1),
        times[-1] + pd.Timedelta(minutes=30),
    )
    axes[-1].xaxis.set_major_formatter(
        mdates.DateFormatter("%d %b\n%H:%M %Z", tz=tz)
    )
    axes[-1].set_xlabel(f"Time ({c['timezone']})")

    # One common legend for all meteogram panels.
    handles, labels = [], []
    for ax in [axes[0], axes[1], axes[2], axes[3], accumulated_rain]:
        h, l = ax.get_legend_handles_labels()
        handles.extend(h)
        labels.extend(l)

    fig.legend(
        handles, labels,
        loc="lower center",
        bbox_to_anchor=(.5, .01),
        ncol=3,
        frameon=False,
    )

    p = c["point"]
    fig.suptitle(
        f"{p.get('name', 'Location')} - ERA5 weather\n"
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


def maps(ds, c, times=None, cities=None, layout="row"):
    """Render ERA5 weather maps.

    ``layout='row'`` preserves the static-output layout: one row per timestamp
    and four columns (temperature, RH, wind, precipitation).

    ``layout='column'`` aligns four maps with the interactive meteogram panels.

    ``layout='2x2'`` is intended for the interactive viewer and renders a
    single timestamp as a compact 2 x 2 square of weather fields.
    """
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature

    projection = ccrs.PlateCarree()
    accumulation = map_accumulations(ds, c)
    ds = ds.assign(precipitation_accumulation=accumulation)

    selected_times = c.get("map_times") if times is None else pd.DatetimeIndex(times)
    if selected_times is not None:
        selected_times = pd.DatetimeIndex(selected_times)
        if selected_times.tz is not None:
            selected_times = selected_times.tz_convert("UTC").tz_localize(None)
        ds = ds.sel(time=selected_times.values)

    count = ds.sizes["time"]
    if layout not in ("row", "2x2", "column"):
        raise ValueError("Map layout must be 'row', '2x2', or 'column'")
    if layout != "row" and count != 1:
        raise ValueError("The column and 2x2 map layouts require exactly one timestamp")

    fields = [
        ("temperature", "2 m temperature (°C)"),
        ("relative_humidity", "2 m relative humidity (%)"),
        ("wind_speed", "10 m wind speed (km/h)"),
        ("precipitation_accumulation", "Accumulated precipitation (mm)"),
    ]

    # Build either the original static layout or a compact 2 x 2 layout for
    # the browser viewer.  In both cases ``axes`` is indexed [time, field].
    if layout == "row":
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
        colorbar_axes = [fig.add_subplot(grid[-1, col]) for col in range(4)]
    elif layout == "column":
        # Match the meteogram's row geometry and physical height. The HTML
        # column ratio matches the figure widths, preserving alignment.
        fig = plt.figure(figsize=(6, 13.5))
        grid = fig.add_gridspec(
            4, 1, height_ratios=[1, 1, 1, 1],
            left=.12, right=.78, bottom=.18, top=.90, hspace=.30,
        )
        axes = np.array([[fig.add_subplot(grid[row, 0], projection=projection)
                          for row in range(4)]], dtype=object)
        colorbar_axes = []
        for ax in axes[0]:
            position = ax.get_position(original=True)
            colorbar_axes.append(fig.add_axes(
                [.83, position.y0, .025, position.height]
            ))
    else:
        fig = plt.figure(figsize=(12, 10.2))
        grid = fig.add_gridspec(
            4, 2,
            height_ratios=[1, .055, 1, .055],
            left=.075, right=.975, top=.90, bottom=.075,
            wspace=.16, hspace=.22,
        )
        map_axes = [
            fig.add_subplot(grid[0, 0], projection=projection),
            fig.add_subplot(grid[0, 1], projection=projection),
            fig.add_subplot(grid[2, 0], projection=projection),
            fig.add_subplot(grid[2, 1], projection=projection),
        ]
        axes = np.array([map_axes], dtype=object)
        colorbar_axes = [
            fig.add_subplot(grid[1, 0]),
            fig.add_subplot(grid[1, 1]),
            fig.add_subplot(grid[3, 0]),
            fig.add_subplot(grid[3, 1]),
        ]

    r = c["region"]
    maps_config = c.get("maps", {})
    if cities is None:
        cities = _load_map_cities(r, maps_config)

    p = c.get("point")
    if p is not None:
        point_lon = p.get("grid_longitude", p["longitude"])
        point_lat = p.get("grid_latitude", p["latitude"])

    admin1 = cfeature.NaturalEarthFeature(
        category="cultural",
        name="admin_1_states_provinces_lines",
        scale="10m",
        facecolor="none",
    )

    artists = [None] * 4
    point_legend_handle = None

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
            if artists[col] is None:
                artists[col] = art

            if name == "precipitation_accumulation":
                start_time = pd.Timestamp(
                    accumulation.accumulation_start.sel(time=t).values
                )
                ax.text(
                    .5, 1.015,
                    f"{start_time:%d %b %H:%M} – {pd.Timestamp(t):%d %b %H:%M} UTC",
                    transform=ax.transAxes, ha="center", fontsize=8,
                )

            if layout == "column":
                ax.text(.5, 1.14 if name == "precipitation_accumulation" else 1.05,
                        label, transform=ax.transAxes, ha="center", va="bottom",
                        fontsize=10)
            elif layout == "2x2":
                ax.set_title(label, fontsize=10, pad=8)
            elif row == 0:
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

            if maps_config.get("coastlines", True):
                ax.coastlines(resolution="10m", linewidth=.8, color="black", zorder=4)
            if maps_config.get("borders", True):
                ax.add_feature(
                    cfeature.BORDERS.with_scale("10m"),
                    linewidth=.55, edgecolor="black", zorder=4,
                )
            if maps_config.get("admin1", False):
                ax.add_feature(admin1, linewidth=.35, edgecolor="0.25", zorder=4)
            if maps_config.get("lakes", True):
                ax.add_feature(
                    cfeature.LAKES.with_scale("10m"),
                    facecolor="none", edgecolor="0.3", linewidth=.45, zorder=4,
                )

            if p is not None:
                point_marker, = ax.plot(
                    point_lon, point_lat,
                    marker="D", markersize=5.5, linestyle="none",
                    markerfacecolor="black", markeredgecolor="white",
                    markeredgewidth=.8,
                    transform=projection, zorder=10,
                )
                if point_legend_handle is None:
                    point_legend_handle = point_marker

            for _, city_name, city_lon, city_lat in cities:
                ax.plot(
                    city_lon, city_lat,
                    marker="o", markersize=2.0, color="black",
                    transform=projection, zorder=8,
                )
                ax.text(
                    city_lon, city_lat, f"  {city_name}",
                    transform=projection,
                    fontsize=7, color="black",
                    ha="left", va="center", zorder=8,
                    bbox={
                        "facecolor": "white", "alpha": .55,
                        "edgecolor": "none", "pad": .5,
                    },
                )

            gl = ax.gridlines(draw_labels=True, alpha=.25, linewidth=.6)
            gl.top_labels = gl.right_labels = False
            gl.xlabel_style = gl.ylabel_style = {"size": 8}

            if layout == "row" and col == 0:
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
        lon, lat = np.meshgrid(wind.longitude.values, wind.latitude.values)
        u = wind.u10.transpose("latitude", "longitude").values * 3.6
        v = wind.v10.transpose("latitude", "longitude").values * 3.6

        axes[row, 2].barbs(
            lon, lat, u, v,
            transform=projection,
            length=4.5, linewidth=.5,
            barb_increments={"half": 5, "full": 10, "flag": 50},
            flip_barb=(lat < 0).ravel(),
            zorder=7,
        )

    for col, (name, label) in enumerate(fields):
        bounds = PALETTES[name][0]
        ticks = bounds[::2] if name == "temperature" else bounds
        cb = fig.colorbar(
            artists[col],
            cax=colorbar_axes[col],
            orientation="vertical" if layout == "column" else "horizontal",
            label=label,
            ticks=ticks,
            spacing="uniform",
            drawedges=True,
        )
        cb.ax.tick_params(labelsize=7)
        if layout != "row":
            cb.set_label(label, fontsize=8)

    if point_legend_handle is not None:
        if layout != "row":
            fig.legend(
                handles=[point_legend_handle], labels=["Meteogram location"],
                loc="lower center" if layout == "column" else "upper left",
                bbox_to_anchor=(.5, .03) if layout == "column" else (.07, .975),
                frameon=True, facecolor="white", edgecolor="0.8", fontsize=8,
            )
        else:
            fig.legend(
                handles=[point_legend_handle], labels=["Meteogram location"],
                loc="upper left", bbox_to_anchor=(.01, .995),
                frameon=True, facecolor="white", edgecolor="0.8", fontsize=10,
            )

    reference_time = _map_reference_time(ds, c)
    title = "ERA5 weather"
    if layout != "row":
        t = pd.Timestamp(ds.time.values[0])
        title += f"\nValid {t:%d %b %Y %H:%M UTC}" if layout == "column" else f" — valid {t:%d %b %Y %H:%M UTC}"
    if reference_time is not None:
        title += f"\nReference time: {reference_time:%d %b %Y %H:%M UTC}"
    fig.suptitle(title, fontsize=13)

    return fig


def _plot_topography_overlay(ax, c, extent, projection):
    """Plot the configured vector overlay and return a legend handle.

    The overlay is intentionally used only when requested by the caller; the
    CLI enables it for the point-centred zoom and leaves the regional
    topography map untouched. Vector data are reprojected to EPSG:4326 before
    plotting.
    """
    overlay = c.get("maps", {}).get("topography_overlay")
    if not overlay:
        return None

    try:
        import geopandas as gpd
        from shapely.geometry import box
        from matplotlib.lines import Line2D
    except ImportError as error:
        raise ImportError(
            "Topography shapefile overlays require geopandas and shapely"
        ) from error

    path = overlay["path"]
    gdf = gpd.read_file(path)
    if gdf.crs is None:
        raise ValueError(f"Topography overlay has no CRS: {path}")
    gdf = gdf.to_crs("EPSG:4326")
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()

    west, east, south, north = extent
    viewport = box(west, south, east, north)
    gdf = gdf[gdf.geometry.intersects(viewport)].copy()
    if gdf.empty:
        print(f"Topography overlay does not intersect the zoom map: {path}")
        return None

    color = overlay.get("edgecolor", "#d7191c")
    linewidth = float(overlay.get("linewidth", 2.0))
    alpha = float(overlay.get("alpha", 1.0))
    zorder = 15

    geom_type = gdf.geometry.geom_type
    polygon_mask = geom_type.isin(["Polygon", "MultiPolygon"])
    line_mask = geom_type.isin(["LineString", "MultiLineString"])
    point_mask = geom_type.isin(["Point", "MultiPoint"])

    if polygon_mask.any():
        gdf.loc[polygon_mask].boundary.plot(
            ax=ax, color=color, linewidth=linewidth, alpha=alpha, zorder=zorder
        )
    if line_mask.any():
        gdf.loc[line_mask].plot(
            ax=ax, color=color, linewidth=linewidth, alpha=alpha, zorder=zorder
        )
    if point_mask.any():
        gdf.loc[point_mask].plot(
            ax=ax, color=color, markersize=max(12, linewidth * 10),
            alpha=alpha, zorder=zorder
        )

    return Line2D(
        [0], [0], color=color, linewidth=linewidth,
        label=str(overlay.get("label", "Area of interest")),
    )


def topography(c, region=None, title=None, overlay=False):
    """Render a static shaded-elevation panel for a region.

    By default this uses ``c['region']`` (the existing general-area map).
    Passing ``region`` allows the same renderer to create a point-centred zoom.
    If ``overlay`` is true, the configured ``maps.topography_overlay`` vector
    is drawn as a highlight on top of the elevation map.
    """
    import cartopy.crs as ccrs
    from matplotlib.colors import LightSource, Normalize
    from matplotlib.cm import ScalarMappable
    from .topography import elevation

    values, extent = elevation(c, region=region)
    west, east, south, north = extent
    finite = values[np.isfinite(values)]
    if not finite.size:
        raise ValueError("No valid topography elevations in the requested region")

    norm = Normalize(min(0, float(finite.min())), max(1, float(finite.max())))
    cmap = plt.get_cmap("terrain")
    dx = ((east - west) / values.shape[1] * 111_320
          * max(.01, np.cos(np.deg2rad((north + south) / 2))))
    dy = (north - south) / values.shape[0] * 111_320
    colors = LightSource(azdeg=315, altdeg=45).shade(
        np.nan_to_num(values), cmap=cmap, norm=norm, dx=dx, dy=dy,
        blend_mode="soft",
    )
    colors[..., 3] = np.isfinite(values)

    projection = ccrs.PlateCarree()
    fig, ax = plt.subplots(figsize=(11, 7), subplot_kw={"projection": projection})
    fig.subplots_adjust(bottom=.16)
    ax.imshow(colors, extent=extent, origin="upper", transform=projection)
    ax.set_extent(extent, crs=projection)

    # Use the same geographic context as the weather maps.
    maps_config = c.get("maps", {})
    if maps_config.get("coastlines", True):
        ax.coastlines(resolution="10m", linewidth=.8, color="black", zorder=8)
    if maps_config.get("borders", True):
        import cartopy.feature as cfeature
        ax.add_feature(
            cfeature.BORDERS.with_scale("10m"),
            linewidth=.55, edgecolor="black", zorder=8,
        )
    if maps_config.get("lakes", True):
        import cartopy.feature as cfeature
        ax.add_feature(
            cfeature.LAKES.with_scale("10m"),
            facecolor="none", edgecolor="0.3", linewidth=.45, zorder=8,
        )

    # Cities use the same Natural Earth source/filtering as the weather maps.
    topo_region = {
        "west": west, "east": east, "south": south, "north": north,
    }
    cities = _load_map_cities(topo_region, maps_config)
    for _, city_name, city_lon, city_lat in cities:
        ax.plot(
            city_lon, city_lat,
            marker="o", markersize=2.2, color="black",
            transform=projection, zorder=12,
        )
        ax.text(
            city_lon, city_lat, f"  {city_name}",
            transform=projection,
            fontsize=7, color="black",
            ha="left", va="center", zorder=12,
            bbox={
                "facecolor": "white",
                "alpha": .6,
                "edgecolor": "none",
                "pad": .5,
            },
        )

    gl = ax.gridlines(draw_labels=True, linewidth=.5, alpha=.3)
    gl.top_labels = gl.right_labels = False

    legend_handles = []
    p = c.get("point")
    if p is not None:
        point_handle, = ax.plot(
            p.get("grid_longitude", p["longitude"]),
            p.get("grid_latitude", p["latitude"]),
            marker="D", markersize=6, linestyle="none",
            markerfacecolor="black", markeredgecolor="white",
            transform=projection, label="Meteogram location", zorder=20,
        )
        legend_handles.append(point_handle)

    if overlay:
        overlay_handle = _plot_topography_overlay(ax, c, extent, projection)
        if overlay_handle is not None:
            legend_handles.append(overlay_handle)

    if legend_handles:
        ax.legend(handles=legend_handles, loc="upper left")

    ax.set_title(title or "Topography — Copernicus GLO-90")
    fig.colorbar(
        ScalarMappable(norm=norm, cmap=cmap), ax=ax, shrink=.8,
        label="Elevation above sea level (m)",
    )
    fig.text(
        .5, .04,
        "Copernicus DEM GLO-90 · Display resampled from ~90 m surface elevation\n"
        "© DLR e.V. 2010–2014 and © Airbus Defence and Space GmbH 2014–2018\n"
        "Provided under COPERNICUS by the European Union and ESA; all rights reserved.",
        ha="center", fontsize=7,
    )
    return fig


def interactive_maps(ds, c, output_path, topography_src=None, topography_zoom_src=None):
    """Create a self-contained HTML viewer synchronized with the meteogram.

    The browser layout places topography first, then a two-column workspace
    with the point meteogram on the left and four vertically aligned maps on the
    right. The shared time controls span both columns below them. JavaScript
    moves a vertical line across the meteogram whenever the map slider changes.
    No web server is required.
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

    interactive_layout = maps_config.get("interactive_map_layout", "column")
    for i, t in enumerate(frame_times, start=1):
        print(f"  Interactive frame {i}/{total}: {t:%Y-%m-%d %H:%M} UTC")
        fig = maps(ds, c, times=[t], cities=cities, layout=interactive_layout)
        buffer = io.BytesIO()
        try:
            fig.savefig(
                buffer,
                format="png",
                dpi=dpi,
                bbox_inches=None if interactive_layout == "column" else "tight",
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

            fig = meteogram(point_ds, c, aligned_maps=interactive_layout == "column")
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
    width: min(1750px, 100%);
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
  .workspace {
    display: grid;
    grid-template-columns: minmax(0, .9fr) minmax(0, 1.35fr);
    gap: 14px;
    align-items: start;
    margin-bottom: 14px;
  }
  .workspace > .panel { margin-bottom: 0; min-width: 0; }
  .workspace.aligned-maps { grid-template-columns: minmax(0, 13fr) minmax(0, 6fr); }
  .workspace.aligned-maps .map-wrap { padding: 0; }
  .workspace.no-meteogram { grid-template-columns: 1fr; }
  .workspace.no-meteogram #meteogram-panel { display: none; }
  .map-wrap {
    min-height: 180px;
    display: grid;
    place-items: center;
    background: white;
    padding: 4px;
  }
  #map-image { display: block; width: 100%; height: auto; }
  .meteogram-wrap {
    position: relative;
    width: 100%;
    margin: 0 auto;
    background: white;
    overflow: hidden;
  }
  #meteogram-image { display: block; width: 100%; height: auto; }
  .meteogram-seek {
    position: absolute;
    inset: 10% 8% 18%;
    cursor: ew-resize;
    touch-action: none;
    user-select: none;
    z-index: 6;
  }
  .meteogram-seek:focus-visible { outline: 2px solid Highlight; }
  #meteogram-line {
    position: absolute;
    top: 10%;
    bottom: 18%;
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
  .topography-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
    padding: 0 16px 16px;
  }
  .topography-item { min-width: 0; }
  .topography-item h3 { margin: 0 0 8px; font-size: .95rem; }
  .topography-item img {
    display: block;
    width: 100%;
    height: auto;
    background: white;
  }
  @media (max-width: 1100px) {
    .workspace, .workspace.aligned-maps { grid-template-columns: 1fr; }
  }
  @media (max-width: 900px) {
    .topography-grid { grid-template-columns: 1fr; }
  }
  .unavailable { padding: 16px; color: GrayText; }
</style>
</head>
<body>
<main>
  <h1 id="page-title">ERA5 weather maps</h1>

  __TOPOGRAPHY_PANEL__

  <section id="time-controls-panel" class="panel" aria-label="Time controls">
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
        The selected valid time updates the four weather maps and the vertical marker in the meteogram.
        Click or drag across the meteogram plots to select the nearest map time.
      </div>
    </div>
  </section>

  <div class="workspace __WORKSPACE_CLASS__">
    <section id="meteogram-panel" class="panel">
      <div class="panel-heading"><h2>Point meteogram</h2></div>
      <div id="meteogram-content"></div>
    </section>

    <section id="spatial-panel" class="panel" aria-label="Interactive ERA5 map viewer">
      <div class="panel-heading"><h2>Spatial fields</h2></div>
      <div class="map-wrap">
        <img id="map-image" alt="ERA5 temperature, relative humidity, wind and accumulated precipitation maps">
      </div>
    </section>
  </div>





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
let meteogramSeek = null;
if (meteogramSrc !== null && meteogramAxisStart !== null && meteogramAxisEnd !== null) {
  const wrap = document.createElement("div");
  wrap.className = "meteogram-wrap";

  const metImage = document.createElement("img");
  metImage.id = "meteogram-image";
  metImage.alt = "ERA5 point meteogram";
  metImage.src = meteogramSrc;
  metImage.draggable = false;

  meteogramLine = document.createElement("div");
  meteogramLine.id = "meteogram-line";
  meteogramLine.setAttribute("aria-hidden", "true");

  wrap.appendChild(metImage);
  wrap.appendChild(meteogramLine);
  meteogramSeek = document.createElement("div");
  meteogramSeek.className = "meteogram-seek";
  meteogramSeek.tabIndex = 0;
  meteogramSeek.setAttribute("role", "slider");
  meteogramSeek.setAttribute("aria-label", "Meteogram valid time");
  meteogramSeek.setAttribute("aria-valuemin", "0");
  meteogramSeek.setAttribute("aria-valuemax", String(frames.length - 1));
  meteogramSeek.title = "Click or drag to select a map time; use arrow keys to step";
  wrap.appendChild(meteogramSeek);
  meteogramContent.appendChild(wrap);

  let activePointer = null;
  function seekAt(clientX) {
    const bounds = meteogramSeek.getBoundingClientRect();
    if (!(bounds.width > 0)) return;
    const fraction = Math.max(0, Math.min(1, (clientX - bounds.left) / bounds.width));
    const timestamp = meteogramAxisStart + fraction * (meteogramAxisEnd - meteogramAxisStart);
    let nearest = 0;
    for (let i = 1; i < frames.length; i++) {
      if (Math.abs(frames[i].timestamp_ms - timestamp) <
          Math.abs(frames[nearest].timestamp_ms - timestamp)) nearest = i;
    }
    showFrame(nearest);
  }
  meteogramSeek.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || activePointer !== null) return;
    event.preventDefault();
    stopPlayback();
    meteogramSeek.focus({preventScroll: true});
    activePointer = event.pointerId;
    meteogramSeek.setPointerCapture(activePointer);
    seekAt(event.clientX);
  });
  meteogramSeek.addEventListener("pointermove", (event) => {
    if (event.pointerId === activePointer) seekAt(event.clientX);
  });
  meteogramSeek.addEventListener("pointerup", (event) => {
    if (event.pointerId !== activePointer) return;
    seekAt(event.clientX);
    activePointer = null;
    meteogramSeek.releasePointerCapture(event.pointerId);
  });
  for (const eventName of ["pointercancel", "lostpointercapture"]) {
    meteogramSeek.addEventListener(eventName, (event) => {
      if (event.pointerId === activePointer) activePointer = null;
    });
  }
  meteogramSeek.addEventListener("keydown", (event) => {
    const targets = {ArrowLeft: index - 1, ArrowDown: index - 1,
                     ArrowRight: index + 1, ArrowUp: index + 1,
                     Home: 0, End: frames.length - 1};
    if (!(event.key in targets)) return;
    event.preventDefault();
    stopPlayback();
    showFrame(targets[event.key]);
  });
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
  if (meteogramSeek !== null) {
    meteogramSeek.setAttribute("aria-valuenow", String(index));
    meteogramSeek.setAttribute("aria-valuetext", frame.utc);
  }
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

    terrain_panel = ""
    terrain_items = []
    if topography_src is not None:
        terrain_items.append(
            '<div class="topography-item">'
            '<h3>General area</h3>'
            '<img alt="Regional shaded elevation map with meteogram location" '
            f'src="{topography_src}">'
            '</div>'
        )
    if topography_zoom_src is not None:
        zoom_radius = maps_config.get("topography_zoom_radius_km", 20.0)
        terrain_items.append(
            '<div class="topography-item">'
            f'<h3>Meteogram-point zoom (±{zoom_radius:g} km)</h3>'
            '<img alt="Point-centred shaded elevation zoom around the meteogram location" '
            f'src="{topography_zoom_src}">'
            '</div>'
        )
    if terrain_items:
        terrain_panel = (
            '<section class="panel" aria-label="Topography">'
            '<div class="panel-heading"><h2>Topography</h2></div>'
            '<div class="topography-grid">' + ''.join(terrain_items) + '</div>'
            '</section>'
        )
    workspace_class = "aligned-maps" if interactive_layout == "column" else ""
    if meteogram_src is None:
        workspace_class += " no-meteogram"
    document = (document.replace("__TOPOGRAPHY_PANEL__", terrain_panel)
                .replace("__WORKSPACE_CLASS__", workspace_class)
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
