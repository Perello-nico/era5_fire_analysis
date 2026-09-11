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
    c.setdefault("formats", ["png"])
    if not c["formats"] or set(c["formats"]) - {"png", "pdf"}:
        raise ValueError("formats must contain png and/or pdf")
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
        step = m.get("every_hours", 6)
        if not isinstance(step, int) or isinstance(step, bool) or step < 1:
            raise ValueError("maps.every_hours must be a positive integer")
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
    """Separate small hourly point requests from sparse regional requests."""
    jobs = []
    if c["mode"] != "point":
        r = c["region"]
        jobs.append(("maps", [r[k] for k in ("north", "west", "south", "east")], c["map_times"]))
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
    if "expver" in ds.dims:
        versions = list(ds.expver.values)
        versions.sort(key=lambda v: (str(v) not in ("1", "0001"), str(v)))
        merged = ds.sel(expver=versions[0], drop=True)
        for v in versions[1:]:
            merged = merged.combine_first(ds.sel(expver=v, drop=True))
        ds = merged
    for name in ("number", "surface"):
        if name in ds.dims and ds.sizes[name] == 1:
            ds = ds.squeeze(name, drop=True)
    if "longitude" in ds.coords:
        ds = ds.assign_coords(longitude=(ds.longitude + 180) % 360 - 180).sortby("longitude")
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
