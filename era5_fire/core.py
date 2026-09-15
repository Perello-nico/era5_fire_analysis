"""Configuration, exact daily CDS requests and meteorological calculations."""
import hashlib
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import xarray as xr
import yaml

DATASET = "reanalysis-era5-single-levels"
VARIABLES = ["2m_temperature", "2m_dewpoint_temperature",
             "10m_u_component_of_wind", "10m_v_component_of_wind",
             "10m_wind_gust_since_previous_post_processing", "total_precipitation"]


def timestamp(value):
    t = pd.Timestamp(value)
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    if t != t.floor("h"):
        raise ValueError("Timestamps must fall on whole hours")
    return t


def load_config(path):
    path = Path(path).resolve()
    c = yaml.safe_load(path.read_text())
    c["start"], c["end"] = timestamp(c["start"]), timestamp(c["end"])
    if c["start"] > c["end"] or c["start"].year < 1940:
        raise ValueError("Require 1940 <= start <= end")
    c.setdefault("mode", "both")
    if c["mode"] not in ("both", "point", "maps"):
        raise ValueError("mode must be both, point, or maps")
    c.setdefault("timezone", "UTC")
    ZoneInfo(c["timezone"])

    # Output selection.  New preferred syntax:
    #   outputs:
    #     png: true
    #     pdf: false
    #     interactive: true
    # The legacy ``formats`` list and ``maps.interactive`` flag are still
    # accepted for backward compatibility.
    outputs = c.get("outputs")
    if outputs is None:
        formats = c.get("formats", ["png"])
        if isinstance(formats, str):
            formats = [formats]
        if formats is None:
            formats = []
        if not isinstance(formats, (list, tuple)) or set(formats) - {"png", "pdf"}:
            raise ValueError("formats must contain only png and/or pdf")
        outputs = {
            "png": "png" in formats,
            "pdf": "pdf" in formats,
        }
        legacy_maps = c.get("maps", {}) if isinstance(c.get("maps", {}), dict) else {}
        outputs["interactive"] = bool(legacy_maps.get("interactive", True if c.get("mode", "both") != "point" else False))
    else:
        if not isinstance(outputs, dict):
            raise ValueError("outputs must be a mapping with png/pdf/interactive booleans")
        outputs = dict(outputs)
        for key in ("png", "pdf", "interactive"):
            outputs.setdefault(key, False)
            if not isinstance(outputs[key], bool):
                raise ValueError(f"outputs.{key} must be true or false")

    static_formats = [fmt for fmt in ("png", "pdf") if outputs.get(fmt, False)]

    # All three flags may be false.  This is a valid data-only workflow:
    # download/process still create point.nc/point.csv and/or maps.nc, while
    # the plotting stage becomes a no-op.
    c["outputs"] = outputs
    c["formats"] = static_formats
    c["write_interactive"] = outputs.get("interactive", False)

    c["output"] = (path.parent / c.get("output", "../output")).resolve()
    if c["mode"] != "maps":
        p = c["point"]
        if not (-90 <= p["latitude"] <= 90 and -180 <= p["longitude"] <= 180):
            raise ValueError("Invalid point coordinates")
    if c["mode"] != "point":
        r = c["region"]
        if not (-90 <= r["south"] < r["north"] <= 90 and
                -180 <= r["west"] < r["east"] <= 180):
            raise ValueError("Invalid region; split regions crossing the antimeridian")
        m = c.setdefault("maps", {})
        if not isinstance(m.setdefault("topography", True), bool):
            raise ValueError("maps.topography must be true or false")
        if not isinstance(m.setdefault("topography_zoom", True), bool):
            raise ValueError("maps.topography_zoom must be true or false")
        zoom_radius = m.setdefault("topography_zoom_radius_km", 20.0)
        if (not isinstance(zoom_radius, (int, float)) or isinstance(zoom_radius, bool)
                or not 1 <= float(zoom_radius) <= 500):
            raise ValueError("maps.topography_zoom_radius_km must be between 1 and 500")

        # Optional shapefile overlay for the point-centred topography only.
        # The path is resolved relative to the YAML file, like ``output``.
        overlay = m.get("topography_overlay")
        if overlay is not None:
            if isinstance(overlay, str):
                overlay = {"path": overlay}
                m["topography_overlay"] = overlay
            if not isinstance(overlay, dict):
                raise ValueError("maps.topography_overlay must be a path string or mapping")
            if "path" not in overlay or not overlay["path"]:
                raise ValueError("maps.topography_overlay.path is required")
            overlay_path = (path.parent / overlay["path"]).resolve()
            if not overlay_path.exists():
                raise FileNotFoundError(f"Topography overlay shapefile not found: {overlay_path}")
            overlay["path"] = overlay_path
            overlay.setdefault("edgecolor", "#d7191c")
            overlay.setdefault("linewidth", 2.0)
            overlay.setdefault("alpha", 1.0)
            overlay.setdefault("label", "Area of interest")
            if (not isinstance(overlay["linewidth"], (int, float))
                    or isinstance(overlay["linewidth"], bool)
                    or float(overlay["linewidth"]) <= 0):
                raise ValueError("maps.topography_overlay.linewidth must be > 0")
            if (not isinstance(overlay["alpha"], (int, float))
                    or isinstance(overlay["alpha"], bool)
                    or not 0 <= float(overlay["alpha"]) <= 1):
                raise ValueError("maps.topography_overlay.alpha must be between 0 and 1")

        step = m.get("every_hours", 6)
        if not isinstance(step, int) or isinstance(step, bool) or step < 1:
            raise ValueError("maps.every_hours must be a positive integer")

        # Interactive HTML output is now controlled primarily by ``outputs``.
        # ``maps.interactive`` is still accepted as a legacy alias when
        # ``outputs`` is not used explicitly.
        interactive = c["write_interactive"]
        m["interactive"] = interactive

        interactive_dpi = m.setdefault("interactive_dpi", 110)
        if (not isinstance(interactive_dpi, int) or isinstance(interactive_dpi, bool)
                or not 60 <= interactive_dpi <= 240):
            raise ValueError("maps.interactive_dpi must be an integer between 60 and 240")

        interactive_interval = m.setdefault("interactive_interval_ms", 900)
        if (not isinstance(interactive_interval, int) or isinstance(interactive_interval, bool)
                or interactive_interval < 100):
            raise ValueError("maps.interactive_interval_ms must be an integer >= 100")
        c["map_times"] = (pd.DatetimeIndex([timestamp(t) for t in m["times"]])
                          if "times" in m else pd.date_range(c["start"], c["end"], freq=f"{step}h"))
        if len(c["map_times"]) == 0 or any((c["map_times"] < c["start"]) | (c["map_times"] > c["end"])):
            raise ValueError("Map timestamps must be nonempty and within start/end")
        c["map_times"] = c["map_times"].unique().sort_values()
    return c


def point_area(p):
    lat, lon = p["latitude"], p["longitude"]
    return [min(90, math.ceil(lat * 4) / 4 + .25),
            max(-180, math.floor(lon * 4) / 4 - .25),
            max(-90, math.floor(lat * 4) / 4 - .25),
            min(180, math.ceil(lon * 4) / 4 + .25)]


def plans(c):
    """Separate hourly point and regional requests."""
    jobs = []
    if c["mode"] != "point":
        r = c["region"]
        jobs.append(("maps", [r[k] for k in ("north", "west", "south", "east")], pd.date_range(c["map_times"][0], c["map_times"][-1], freq="h")))
    if c["mode"] != "maps":
        jobs.append(("point", point_area(c["point"]), pd.date_range(c["start"], c["end"], freq="h")))
    result = []
    for kind, area, times in jobs:
        for day in times.normalize().unique():
            selected = times[times.normalize() == day]
            request = dict(product_type=["reanalysis"], variable=VARIABLES,
                           year=[day.strftime("%Y")], month=[day.strftime("%m")],
                           day=[day.strftime("%d")], time=selected.strftime("%H:%M").tolist(),
                           area=area, data_format="netcdf", download_format="zip")
            key = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()[:16]
            result.append((kind, request, c["output"] / "raw" / f"{kind}-{day:%Y%m%d}-{key}.zip"))
    return result


def normalize(ds):
    if "valid_time" in ds.dims:
        ds = ds.rename({"valid_time": "time"})
    # ERA5 / ERA5T expver handling
    if "expver" in ds.dims:
        versions = list(ds.expver.values)
        # Prefer final ERA5 (expver=1) over ERA5T (expver=5)
        versions.sort(
            key=lambda v: (str(v) not in ("1", "0001"), str(v))
        )
        merged = ds.sel(expver=versions[0], drop=True)
        for v in versions[1:]:
            other = ds.sel(expver=v, drop=True)
            merged = merged.combine_first(other)

        ds = merged
    # expver may instead be just a scalar coordinate.
    # Once the data have been selected, we don't need this metadata
    # for subsequent concatenation across days.
    if "expver" in ds.coords:
        ds = ds.drop_vars("expver")
    for name in ("number", "surface"):
        if name in ds.dims and ds.sizes[name] == 1:
            ds = ds.squeeze(name, drop=True)
    if "longitude" in ds.coords:
        ds = ds.assign_coords(
            longitude=(ds.longitude + 180) % 360 - 180
        ).sortby("longitude")
    return ds.sortby("time")


def derive(ds):
    required = ["t2m", "d2m", "u10", "v10", "fg10", "tp"]
    missing = set(required) - set(ds.data_vars)
    if missing:
        raise ValueError(f"Missing ERA5 variables: {sorted(missing)}")
    wind_units = {"m s**-1", "m s-1", "m/s"}
    for name, units in [("t2m", {"K"}), ("d2m", {"K"}), ("tp", {"m"}),
                        ("u10", wind_units), ("v10", wind_units), ("fg10", wind_units)]:
        if ds[name].attrs.get("units") not in units:
            raise ValueError(f"Unexpected units for {name}: {ds[name].attrs.get('units')}")
    t, td = ds.t2m - 273.15, ds.d2m - 273.15
    # Magnus approximation over liquid water, including below freezing.
    es = lambda x: .61094 * np.exp(17.625 * x / (243.04 + x))
    speed = np.hypot(ds.u10, ds.v10)
    fields = {
        "temperature": (t, "degC"), "dewpoint": (td, "degC"),
        "relative_humidity": ((100 * es(td) / es(t)).clip(0, 100), "%"),
        "vpd": ((es(t) - es(td)).clip(min=0), "kPa"),
        "wind_speed": (speed, "m s-1"),
        "wind_direction": (((270 - np.degrees(np.arctan2(ds.v10, ds.u10))) % 360).where(speed >= .1), "degree"),
        "wind_gust": (ds.fg10, "m s-1"),
        "precipitation": (ds.tp * 1000, "mm"),
        "u10": (ds.u10, "m s-1"), "v10": (ds.v10, "m s-1")}
    out = xr.Dataset({k: v[0] for k, v in fields.items()})
    for k, (_, unit) in fields.items():
        out[k].attrs = {"units": unit}
    out.precipitation.attrs["description"] = "Water equivalent precipitation in the hour ending at time; no deaccumulation"
    out.wind_gust.attrs["description"] = "Maximum gust since previous post-processing (preceding hour)"
    out.attrs = {"source": DATASET, "time_zone": "UTC", "humidity_method": "Magnus over liquid water"}
    if bool((out.precipitation < -1e-5).any()):
        raise ValueError("Negative precipitation encountered")
    out["precipitation"] = out.precipitation.clip(min=0, keep_attrs=True)
    return out
