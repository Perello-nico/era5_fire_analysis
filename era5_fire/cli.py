"""Command line workflow. Downloads are cached by request content."""
import argparse
import json
from pathlib import Path
import tempfile
import time
import zipfile

import pandas as pd
import xarray as xr

from .core import DATASET, derive, load_config, normalize, plans


def download(jobs):
    import cdsapi
    client = None
    for _, request, path in jobs:
        if path.exists():
            print(f"Cached: {path.name}")
            continue
        if client is None:
            client = cdsapi.Client()
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".part")
        for attempt in range(3):
            try:
                client.retrieve(DATASET, request, str(partial))
                # Check the payload before committing it to the cache.
                read_payload(partial)
                partial.replace(path)
                path.with_suffix(".json").write_text(json.dumps({"dataset": DATASET, "request": request}, indent=2))
                break
            except Exception:
                partial.unlink(missing_ok=True)
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)


def read_payload(path):
    def read(p):
        with xr.open_dataset(p) as ds:
            return normalize(ds.load())
    if not zipfile.is_zipfile(path):
        return read(path)
    parts = []
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(path) as archive:
        for i, name in enumerate(archive.namelist()):
            if name.endswith(".nc"):
                # Do not extract archive-controlled paths.
                p = Path(tmp) / f"{i}.nc"
                p.write_bytes(archive.read(name))
                parts.append(read(p))
    if not parts:
        raise ValueError(f"No NetCDF files found in {path}")
    return xr.merge(parts, compat="no_conflicts", join="outer")


def process(c, jobs):
    for kind in dict.fromkeys(j[0] for j in jobs):
        files = [p for k, _, p in jobs if k == kind]
        missing = [str(p) for p in files if not p.exists()]
        if missing:
            raise FileNotFoundError(f"Run download first. Missing: {missing[0]}")
        ds = xr.concat([read_payload(p) for p in files], dim="time").sortby("time")
        expected = (pd.date_range(c["map_times"][0], c["map_times"][-1], freq="h")
                    if kind == "maps" else pd.date_range(c["start"], c["end"], freq="h"))
        expected = expected.tz_localize(None)
        actual = pd.DatetimeIndex(ds.time.values)
        if actual.has_duplicates or not actual.equals(expected):
            raise ValueError(f"{kind}: returned timestamps differ from the requested hours")
        if kind == "point":
            p = c["point"]
            ds = ds.sel(latitude=p["latitude"], longitude=p["longitude"], method="nearest")
        out = derive(ds)
        for name in out.data_vars:
            # Wind direction is intentionally undefined during calm conditions.
            if name != "wind_direction" and bool(out[name].isnull().any()):
                raise ValueError(f"{kind}: missing values in {name}")
        if kind == "point":
            out.attrs.update(requested_latitude=p["latitude"], requested_longitude=p["longitude"])
            # Full windows only; first 23 hours have no 24-hour total.
            out["precipitation_24h"] = out.precipitation.rolling(time=24, min_periods=24).sum()
            out.precipitation_24h.attrs = {"units": "mm", "description": "Preceding 24 hours; missing until a full window is available"}
            table = out.to_dataframe()
            table.index = table.index.tz_localize("UTC")
            table.to_csv(c["output"] / "point.csv")
        out.time.encoding = {"units": "hours since 1970-01-01", "dtype": "int64"}
        out.to_netcdf(c["output"] / f"{kind}.nc")
        print(f"Processed {kind}: {len(expected)} timestamps")


def save(fig, base, formats):
    for extension in formats:
        fig.savefig(base.with_suffix(f".{extension}"), dpi=160, bbox_inches=None)


def plot(c):
    static_formats = c.get("formats", [])
    write_interactive = bool(c.get("write_interactive", False)) and c["mode"] != "point"

    # Data-only workflow: ``run`` still downloads/processes NetCDF/CSV files,
    # but there is nothing to render and no figures directory is created.
    if not static_formats and not write_interactive:
        print("Plotting skipped: no static or interactive outputs requested")
        return

    from .plotting import interactive_maps, meteogram, maps, topography, plt
    from .topography import point_zoom_region
    import base64
    import io

    dest = c["output"] / "figures"
    dest.mkdir(parents=True, exist_ok=True)
    maps_config = c.get("maps", {})

    # Point meteogram static output.
    if c["mode"] != "maps" and static_formats:
        with xr.open_dataset(c["output"] / "point.nc") as source:
            ds = source.load()
        fig = meteogram(ds, c)
        try:
            save(fig, dest / "meteogram", static_formats)
        finally:
            plt.close(fig)

    # Point-only mode has no spatial products or interactive map viewer.
    if c["mode"] == "point":
        return

    with xr.open_dataset(c["output"] / "maps.nc") as source:
        maps_ds = source.load()

    # Static combined weather maps.
    if static_formats:
        fig = maps(maps_ds, c)
        try:
            save(fig, dest / "maps", static_formats)
        finally:
            plt.close(fig)

    topography_src = None
    topography_zoom_src = None

    def figure_to_data_uri(fig, dpi=140):
        buffer = io.BytesIO()
        fig.savefig(buffer, format="png", dpi=dpi, facecolor="white")
        return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")

    # Topography products: save to disk only if a static format is requested;
    # otherwise render only in memory when required by the interactive HTML.
    if maps_config.get("topography", True) and (static_formats or write_interactive):
        fig = topography(c)
        try:
            if static_formats:
                save(fig, dest / "topography", static_formats)
            if write_interactive:
                topography_src = figure_to_data_uri(fig)
        finally:
            plt.close(fig)

        if maps_config.get("topography_zoom", True) and c.get("point") is not None:
            radius_km = float(maps_config.get("topography_zoom_radius_km", 20.0))
            zoom_region = point_zoom_region(c, radius_km=radius_km)
            fig = topography(
                c,
                region=zoom_region,
                title=f"Topography — {radius_km:g} km radius around meteogram point",
            )
            try:
                if static_formats:
                    save(fig, dest / "topography_zoom", static_formats)
                if write_interactive:
                    topography_zoom_src = figure_to_data_uri(fig)
            finally:
                plt.close(fig)

    if write_interactive:
        html_path = interactive_maps(
            maps_ds,
            c,
            dest / "maps_interactive.html",
            topography_src=topography_src,
            topography_zoom_src=topography_zoom_src,
        )
        print(f"Interactive maps: {html_path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["plan", "download", "process", "plot", "run"])
    parser.add_argument("--config", default="example/example.yaml")
    args = parser.parse_args()
    try:
        c = load_config(args.config)
        jobs = plans(c)
        if args.command == "plan":
            print(json.dumps([{"kind": k, "dataset": DATASET, "request": r, "target": str(p)} for k, r, p in jobs], indent=2))
            return
        c["output"].mkdir(parents=True, exist_ok=True)
        if args.command in ("download", "run"):
            download(jobs)
        if args.command in ("process", "run"):
            process(c, jobs)
        if args.command in ("plot", "run"):
            plot(c)
    except (ValueError, KeyError, FileNotFoundError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()