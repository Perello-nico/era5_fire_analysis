"""Static meteograms styled after ~/Codes/meteogram, and fire-weather maps."""
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
    cmap = cmap.with_extremes(under=colors[0], over=colors[-1], bad=(0, 0, 0, 0))
    return cmap, BoundaryNorm(boundaries, cmap.N)


def meteogram(ds, c):
    """Three panels: T/Td/RH, wind/gust/direction, and precipitation."""
    times = pd.DatetimeIndex(ds.time.values).tz_localize("UTC").tz_convert(c["timezone"])
    tz = ZoneInfo(c["timezone"])
    fig, axes = plt.subplots(3, 1, figsize=(13, 9), sharex=True,
                             gridspec_kw={"height_ratios": [1.2, 1, .75]})
    fig.subplots_adjust(left=.08, right=.92, bottom=.1, top=.8, hspace=.35)
    rh = axes[0].twinx()
    axes[0].plot(times, ds.temperature, color="#ff3b30", lw=2, label="Temperature")
    axes[0].plot(times, ds.dewpoint, color="#9b6bd6", lw=2, label="Dew point")
    rh.plot(times, ds.relative_humidity, color="#0c53e0", lw=2, ls=":", label="Relative humidity")
    rh.set(ylabel="Relative humidity (%)", ylim=(0, 100))
    axes[0].set(ylabel="°C", title="Temperature and relative humidity")
    axes[0].margins(y=.15)
    speed, gust = ds.wind_speed.values * 3.6, ds.wind_gust.values * 3.6
    axes[1].plot(times, speed, color="#2ecc71", lw=2, label="Wind speed")
    axes[1].plot(times, gust, color="#198754", lw=1.5, ls="--", label="Hourly maximum gust")
    maximum = max(float(np.nanmax(speed)), float(np.nanmax(gust)), 1)
    # Equal-length arrows show direction of motion in screen coordinates.
    stride = max(1, int(np.ceil(len(times) / 48)))
    direction = np.deg2rad(ds.wind_direction.values[::stride])
    axes[1].quiver(mdates.date2num(times[::stride]), np.full(len(direction), maximum * 1.12),
                   -np.sin(direction), -np.cos(direction), angles="uv", scale_units="inches",
                   scale=7, width=.002, pivot="middle", color="#1b1e1b")
    axes[1].set(ylabel="km/h", ylim=(0, maximum * 1.28), title="Wind — arrows show direction of motion")
    axes[2].bar(times, ds.precipitation, width=-1/24, align="edge", color="#4682b4", label="Hourly precipitation")
    axes[2].set(ylabel="mm", title="Precipitation in the preceding hour", ylim=(0, None))
    # Same fixed 18:00–06:00 bands as the reference project, in display timezone.
    # These are clock-hour bands, not calculated sunrise/sunset.
    days = pd.date_range(times[0].normalize() - pd.DateOffset(days=1),
                         times[-1].normalize() + pd.DateOffset(days=1), freq="D")
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
    axes[-1].set_xlim(times[0] - pd.Timedelta(hours=1), times[-1] + pd.Timedelta(minutes=30))
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%d %b\n%H:%M %Z", tz=tz))
    axes[-1].set_xlabel(f"Time ({c['timezone']})")
    handles, labels = [], []
    for ax in [axes[0], rh, axes[1], axes[2]]:
        h, l = ax.get_legend_handles_labels()
        handles.extend(h)
        labels.extend(l)
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(.5, .9), ncol=3, frameon=False)
    p = c["point"]
    fig.suptitle(f"{p.get('name', 'Location')} — ERA5\n"
                 f"Requested {p['latitude']:.3f}, {p['longitude']:.3f}; "
                 f"grid {float(ds.latitude):.3f}, {float(ds.longitude):.3f}", y=.98)
    return fig


def maps(ds, c):
    """One row per requested timestamp, three columns, shared discrete legends."""
    import cartopy.crs as ccrs
    projection = ccrs.PlateCarree()
    if "map_times" in c:
        ds = ds.sel(time=c["map_times"].tz_localize(None).values)
    count = ds.sizes["time"]
    fig = plt.figure(figsize=(16, 3.8 * count + 1.5))
    grid = fig.add_gridspec(count + 1, 3, height_ratios=[1] * count + [.06],
                           left=.10, right=.98, top=.90 if count == 1 else .94,
                           bottom=.08 if count == 1 else .045, wspace=.17, hspace=.22)
    axes = np.array([[fig.add_subplot(grid[row, col], projection=projection)
                      for col in range(3)] for row in range(count)])
    fields = [("temperature", "2 m temperature (°C)"),
              ("relative_humidity", "2 m relative humidity (%)"),
              ("wind_speed", "10 m wind speed (km/h)")]
    r = c["region"]
    artists = []
    for row, t in enumerate(ds.time.values):
        frame = ds.sel(time=t)
        for col, (name, label) in enumerate(fields):
            ax = axes[row, col]
            cmap, norm = palette(name)
            values = frame[name].transpose("latitude", "longitude")
            if name == "wind_speed":
                values = values * 3.6
            art = ax.pcolormesh(frame.longitude, frame.latitude, values,
                                transform=projection, shading="auto", cmap=cmap, norm=norm)
            if row == 0:
                artists.append(art)
                position = ax.get_position()
                fig.text((position.x0 + position.x1) / 2, position.y1 + .015,
                         label, ha="center", va="bottom", fontsize=12)
            ax.set_extent([r["west"], r["east"], r["south"], r["north"]], crs=projection)
            if c.get("maps", {}).get("coastlines", True):
                ax.coastlines(resolution="110m", linewidth=.6)
            gl = ax.gridlines(draw_labels=True, alpha=.25)
            gl.top_labels = gl.right_labels = False
            gl.xlabel_style = gl.ylabel_style = {"size": 8}
            if col == 0:
                position = ax.get_position()
                fig.text(.025, (position.y0 + position.y1) / 2,
                         f"{pd.Timestamp(t):%d %b %Y}\n{pd.Timestamp(t):%H:%M} UTC",
                         rotation=90, ha="center", va="center", fontsize=10)
        stride = max(1, int(np.ceil(max(frame.sizes["latitude"], frame.sizes["longitude"]) / 15)))
        wind = frame.isel(latitude=slice(None, None, stride), longitude=slice(None, None, stride))
        lon, lat = np.meshgrid(wind.longitude, wind.latitude)
        # Explicit km/h increments: half barb=5, full barb=10, pennant=50.
        axes[row, 2].barbs(lon, lat, wind.u10.transpose("latitude", "longitude").values * 3.6,
                          wind.v10.transpose("latitude", "longitude").values * 3.6,
                          transform=projection, length=4.5, linewidth=.5,
                          barb_increments={"half": 5, "full": 10, "flag": 50},
                          flip_barb=lat < 0)
    for col, (name, label) in enumerate(fields):
        bounds = PALETTES[name][0]
        ticks = bounds[::2] if name == "temperature" else bounds
        cb = fig.colorbar(artists[col], cax=fig.add_subplot(grid[-1, col]), orientation="horizontal",
                          label=label, ticks=ticks, spacing="uniform", drawedges=True)
        cb.ax.tick_params(labelsize=7)
    fig.suptitle("ERA5 fire weather\nWind barbs in km/h: half = 5, full = 10, pennant = 50", fontsize=13)
    return fig
