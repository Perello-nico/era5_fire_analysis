"""Cached Copernicus GLO-90 elevation, resampled for regional display."""
import math
from pathlib import Path
import shutil
from urllib.request import urlopen

import numpy as np

BASE_URL = "https://copernicus-dem-90m.s3.amazonaws.com"


def _cached_download(url, path):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(path.suffix + ".part")
        try:
            with urlopen(url, timeout=60) as source, partial.open("wb") as target:
                shutil.copyfileobj(source, target)
            partial.replace(path)
        finally:
            partial.unlink(missing_ok=True)
    return path


def elevation(c):
    """Return a north-up elevation grid and its west/east/south/north extent."""
    import rasterio
    from rasterio.transform import from_bounds
    from rasterio.warp import reproject, Resampling

    r = c["region"]
    west, east, south, north = (r[k] for k in ("west", "east", "south", "north"))
    cache = Path(c["output"]) / "raw" / "topography"
    listing = _cached_download(f"{BASE_URL}/tileList.txt", cache / "tileList.txt")
    available = set(listing.read_text().split())
    # Bound display memory independently of domain size and native resolution.
    width = min(1200, max(2, math.ceil((east - west) * 1200)))
    height = min(1200, max(2, math.ceil((north - south) * 1200)))
    transform = from_bounds(west, south, east, north, width, height)
    result = np.full((height, width), np.nan, dtype="float32")
    for lat in range(math.floor(south), math.ceil(north)):
        for lon in range(math.floor(west), math.ceil(east)):
            name = (f"Copernicus_DSM_COG_30_{'N' if lat >= 0 else 'S'}{abs(lat):02d}_00_"
                    f"{'E' if lon >= 0 else 'W'}{abs(lon):03d}_00_DEM")
            if name not in available and name + '/' not in available:
                # The provider omits ocean-only tiles.
                continue
            path = _cached_download(f"{BASE_URL}/{name}/{name}.tif", cache / f"{name}.tif")
            with rasterio.open(path) as src:
                reproject(
                    rasterio.band(src, 1), result,
                    src_transform=src.transform, src_crs=src.crs,
                    src_nodata=src.nodata, dst_transform=transform,
                    dst_crs="EPSG:4326", dst_nodata=np.nan,
                    resampling=Resampling.bilinear, init_dest_nodata=False,
                )
    # Uncovered ocean is zero; native missing pixels remain visibly masked.
    ys = north - (np.arange(height) + .5) * (north - south) / height
    xs = west + (np.arange(width) + .5) * (east - west) / width
    for lat in range(math.floor(south), math.ceil(north)):
        for lon in range(math.floor(west), math.ceil(east)):
            name = (f"Copernicus_DSM_COG_30_{'N' if lat >= 0 else 'S'}{abs(lat):02d}_00_"
                    f"{'E' if lon >= 0 else 'W'}{abs(lon):03d}_00_DEM")
            if name not in available and name + '/' not in available:
                result[np.ix_((ys >= lat) & (ys < lat + 1), (xs >= lon) & (xs < lon + 1))] = 0
    return result, (west, east, south, north)
