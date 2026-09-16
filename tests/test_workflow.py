import numpy as np
import pandas as pd
import pytest
import xarray as xr
import yaml
import zipfile
from era5_fire.core import derive, load_config, plans
from era5_fire.cli import process, plot


def data(times):
    def field(value, unit):
        return (("time", "latitude", "longitude"), np.full((len(times), 3, 3), value, dtype=float), {"units": unit})
    return xr.Dataset({"t2m": field(293.15, "K"), "d2m": field(293.15, "K"),
        "u10": field(0, "m s**-1"), "v10": field(-5, "m s**-1"),
        "fg10": field(8, "m s**-1"), "tp": field(.001, "m")},
        coords={"time": times, "latitude": [39, 38, 37], "longitude": [12, 13, 14]})


def test_meteorology():
    ds = data(pd.date_range("2023-01-01", periods=4, freq="h"))
    ds["u10"][:] = np.array([0, -5, 0, 5])[:, None, None]
    ds["v10"][:] = np.array([-5, 0, 5, 0])[:, None, None]
    out = derive(ds)
    np.testing.assert_allclose(out.temperature, 20)
    np.testing.assert_allclose(out.relative_humidity, 100)
    np.testing.assert_allclose(out.vpd, 0)
    np.testing.assert_allclose(out.wind_speed, 5)
    np.testing.assert_allclose(out.wind_direction[:, 0, 0], [0, 90, 180, 270])
    np.testing.assert_allclose(out.precipitation, 1)
    ds["u10"][:] = 0
    ds["v10"][:] = 0
    assert derive(ds).wind_direction.isnull().all()
    ds["d2m"][:] = 283.15
    np.testing.assert_allclose(derive(ds).relative_humidity, 52.54, atol=.1)


def test_pipeline(tmp_path, monkeypatch):
    monkeypatch.setattr("era5_fire.topography.elevation", lambda c, region=None: (
        np.arange(100, dtype=float).reshape(10, 10), (12, 14, 37, 39)))
    path = tmp_path / "case.yaml"
    path.write_text(yaml.safe_dump({"start": "2023-07-31T12:00Z", "end": "2023-08-01T12:00Z",
        "point": {"latitude": 38.1, "longitude": 13.1},
        "region": {"north": 39, "south": 37, "west": 12, "east": 14},
        "maps": {"every_hours": 12, "topography": True, "coastlines": False, "cities": False, "borders": False, "lakes": False}, "output": "out"}))
    c = load_config(path)
    jobs = plans(c)
    requests = [r for k, r, _ in jobs if k == "point"]
    assert [r["month"] for r in requests] == [["07"], ["08"]]
    assert sum(len(r["time"]) for r in requests) == 25
    assert sum(len(r["time"]) for k, r, _ in jobs if k == "maps") == 25
    for _, request, target in jobs:
        target.parent.mkdir(parents=True, exist_ok=True)
        day = "-".join(request[k][0] for k in ("year", "month", "day"))
        ds = data(pd.DatetimeIndex([f"{day}T{t}" for t in request["time"]])).rename(time="valid_time")
        with zipfile.ZipFile(target, "w") as archive:
            for name, variables in {"instant": ["t2m", "d2m", "u10", "v10"], "accum": ["tp"], "max": ["fg10"]}.items():
                file = tmp_path / f"{name}.nc"
                ds[variables].to_netcdf(file)
                archive.write(file, f"nested/{name}.nc")
    process(c, jobs)
    with xr.open_dataset(c["output"] / "point.nc") as ds:
        assert float(ds.latitude) == 38
        assert np.isnan(ds.precipitation_24h.values[22])
        assert ds.precipitation_24h.values[23] == 24
    plot(c)
    assert len(list((c["output"] / "figures").glob("*.png"))) == 4
    html = (c["output"] / "figures" / "maps_interactive.html").read_text()
    assert html.index('aria-label="Topography"') < html.index('id="time-controls-panel"') < html.index('id="meteogram-panel"')
    assert 'aria-label="Topography"' in html
    assert html.index('aria-label="Topography"') < html.index('id="map-image"')
    assert (c["output"] / "point.csv").exists()


def test_invalid_time(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text('start: "2023-01-01T00:30Z"\nend: "2023-01-02"')
    with pytest.raises(ValueError, match="whole hours"):
        load_config(path)


def test_expver_preference():
    from era5_fire.core import normalize
    ds = data(pd.date_range("2023-01-01", periods=2, freq="h"))
    preliminary = ds.copy(deep=True)
    preliminary["t2m"][:] = 300
    final = ds.copy(deep=True)
    final["t2m"][0] = np.nan
    combined = xr.concat([preliminary, final], pd.Index([5, 1], name="expver"))
    out = normalize(combined)
    np.testing.assert_allclose(out.t2m[0], 300)
    np.testing.assert_allclose(out.t2m[1], 293.15)


def test_download_cache_and_retry(tmp_path, monkeypatch):
    import cdsapi
    from era5_fire.cli import download
    calls = []
    class Client:
        def retrieve(self, dataset, request, target):
            calls.append(request)
            if len(calls) == 1:
                raise OSError("temporary failure")
            data(pd.date_range("2023-01-01", periods=1)).to_netcdf(target)
    monkeypatch.setattr(cdsapi, "Client", Client)
    monkeypatch.setattr("era5_fire.cli.time.sleep", lambda _: None)
    target = tmp_path / "raw" / "test.zip"
    jobs = [("point", {"test": "request"}, target)]
    download(jobs)
    download(jobs)
    assert len(calls) == 2
    assert target.with_suffix(".json").exists()
    assert not target.with_suffix(".part").exists()


def test_plot_palettes_and_layout():
    from matplotlib.quiver import Barbs
    from era5_fire.plotting import maps, meteogram, palette, plt
    from matplotlib.colors import to_rgba
    cmap, norm = palette("wind_speed")
    assert cmap(norm(0))[-1] == 0
    assert cmap(norm(9.99))[-1] == 0
    assert cmap(norm(10)) == to_rgba("#fff9b0")
    assert cmap(norm(20)) == to_rgba("#ffff4d")
    assert cmap(norm(120)) == cmap(norm(95))
    cmap, norm = palette("relative_humidity")
    assert cmap(norm(0)) == cmap(norm(5))
    assert cmap(norm(100)) == cmap(norm(99))
    times = pd.date_range("2023-01-01", periods=2, freq="h")
    ds = derive(data(times))
    c = {"timezone": "Europe/Rome", "point": {"latitude": 38, "longitude": 13},
         "region": {"north": 39, "south": 37, "west": 12, "east": 14},
         "maps": {"coastlines": False, "cities": False, "borders": False, "lakes": False}}
    fig = maps(ds, c)
    assert len(fig.axes) == 12  # 2 x 4 maps + 4 shared colorbars
    for ax in [fig.axes[2], fig.axes[6]]:
        barbs = next(artist for artist in ax.collections if isinstance(artist, Barbs))
        np.testing.assert_allclose(barbs.v, -18)  # m/s converted to km/h
        np.testing.assert_allclose(ax.collections[0].get_array(), 18)
    plt.close(fig)
    column = maps(ds, c, times=times[:1], layout="column")
    aligned = meteogram(ds.sel(latitude=38, longitude=13), c, aligned_maps=True)
    column.canvas.draw()
    aligned.canvas.draw()
    # Compare rendered row centres; Cartopy may shrink maps to preserve aspect.
    for map_ax, point_ax in zip(column.axes[:4], aligned.axes[:4]):
        map_box, point_box = map_ax.get_position(), point_ax.get_position()
        assert (map_box.y0 + map_box.y1) / 2 == pytest.approx(
            (point_box.y0 + point_box.y1) / 2)
    for figure in (column, aligned):
        boxes = [ax.get_position() for ax in figure.axes[:4]]
        np.testing.assert_allclose([box.height for box in boxes], boxes[0].height)
        np.testing.assert_allclose([box.width for box in boxes], boxes[0].width)
    assert column.get_figheight() == aligned.get_figheight()
    assert aligned.get_figheight() < 16
    plt.close(column)
    plt.close(aligned)
    fig = meteogram(ds.sel(latitude=38, longitude=13), c)
    assert len(fig.axes) == 5  # Three panels plus RH and accumulated rain axes
    labels = [line.get_label() for ax in fig.axes for line in ax.lines]
    assert "Relative humidity" in labels
    rain_line = next(line for ax in fig.axes for line in ax.lines
                     if line.get_label() == "Accumulated precipitation")
    np.testing.assert_allclose(rain_line.get_ydata(), [1, 2])
    assert not any("VPD" in label for label in labels)
    plt.close(fig)


def test_rain_accumulation():
    from era5_fire.plotting import map_accumulations, palette
    times = pd.date_range("2023-07-31T22:00", periods=7, freq="h")
    ds = derive(data(times))
    ds.precipitation[:] = np.arange(1, 8)[:, None, None]
    c = {"map_times": times[[0, 2, 6]].tz_localize("UTC").tz_convert("Europe/Rome")}
    rain = map_accumulations(ds, c)
    np.testing.assert_allclose(rain[:, 0, 0], [1, 6, 28])
    assert (rain.accumulation_start.values ==
            (times[0] - pd.Timedelta(hours=1)).to_datetime64()).all()
    with pytest.raises(ValueError, match="every intervening hour"):
        map_accumulations(ds.isel(time=[0, 2, 6]), c)
    ds.precipitation[3, 0, 0] = np.nan
    assert np.isnan(map_accumulations(ds, c)[2, 0, 0])
    cmap, norm = palette("precipitation_accumulation")
    assert cmap(norm(.49))[-1] == 0
    assert cmap(norm(.5))[-1] == 1
    assert cmap(norm(250)) == cmap(norm(300))


def test_topography_panel(tmp_path, monkeypatch):
    import rasterio
    from rasterio.transform import from_bounds
    from era5_fire.topography import elevation
    from era5_fire.plotting import topography, plt

    cache = tmp_path / "raw" / "topography"
    cache.mkdir(parents=True)
    name = "Copernicus_DSM_COG_30_N44_00_E005_00_DEM"
    (cache / "tileList.txt").write_text(name + '\n')
    with rasterio.open(cache / f"{name}.tif", "w", driver="GTiff",
                       width=10, height=10, count=1, dtype="float32",
                       crs="EPSG:4326", transform=from_bounds(5, 44, 6, 45, 10, 10)) as dst:
        dst.write(np.full((10, 10), 750, dtype="float32"), 1)
    c = {"output": tmp_path, "region": {"west": 5.1, "east": 5.9, "south": 44.1, "north": 44.9},
         "point": {"longitude": 5.4, "latitude": 44.5}}
    values, extent = elevation(c)
    np.testing.assert_allclose(values, 750)
    assert extent == (5.1, 5.9, 44.1, 44.9)
    fig = topography(c)
    fig.savefig(tmp_path / "terrain.png")
    assert fig.axes[0].get_legend().get_texts()[0].get_text() == "Meteogram location"
    assert fig.axes[1].get_ylabel() == "Elevation above sea level (m)"
    plt.close(fig)


@pytest.mark.parametrize("terrain,weather", [(True, True), (True, False), (False, True), (False, False)])
def test_overlay_map_scope(tmp_path, monkeypatch, terrain, weather):
    import geopandas as gpd
    from shapely.geometry import Polygon
    from era5_fire.plotting import maps, topography, plt

    shape = tmp_path / "perimeter.geojson"
    gpd.GeoDataFrame(geometry=[Polygon([(12.5, 37.5), (13.5, 37.5),
                                       (13.5, 38.5), (12.5, 38.5)])],
                     crs="EPSG:4326").to_file(shape)
    c = {"region": {"west": 12, "east": 14, "south": 37, "north": 39},
         "maps": {"coastlines": False, "borders": False, "lakes": False,
                  "cities": False, "overlay": {
                      "path": shape, "topography": terrain, "weather": weather,
                      "label": "Fire perimeter"}}}
    monkeypatch.setattr("era5_fire.topography.elevation", lambda c, region=None: (
        np.arange(100, dtype=float).reshape(10, 10), (12, 14, 37, 39)))
    ds = derive(data(pd.date_range("2023-01-01", periods=1, freq="h")))
    for layout in ("row", "column", "2x2"):
        fig = maps(ds, c, cities=[], layout=layout)
        assert bool(fig.legends) == weather
        # Each panel has a mesh; the overlay adds a boundary collection.
        for ax in fig.axes:
            if hasattr(ax, "projection"):
                boundaries = [a for a in ax.collections
                              if type(a).__name__ == "LineCollection"]
                assert bool(boundaries) == weather
        plt.close(fig)
    for zoom in (False, True):
        fig = topography(c, region=c["region"] if zoom else None)
        assert (fig.axes[0].get_legend() is not None) == terrain
        plt.close(fig)


def test_overlay_config_switches(tmp_path):
    path = tmp_path / "case.yaml"
    config = {"start": "2023-01-01", "end": "2023-01-02", "mode": "maps",
              "region": {"west": 12, "east": 14, "south": 37, "north": 39},
              "maps": {"overlay": {"topography": False, "weather": False, "path": "missing.shp"}}}
    path.write_text(yaml.safe_dump(config))
    assert load_config(path)["maps"]["overlay"]["weather"] is False
    for key in ("topography", "weather"):
        config["maps"]["overlay"] = {key: "true"}
        path.write_text(yaml.safe_dump(config))
        with pytest.raises(ValueError, match=key):
            load_config(path)


def test_overlay_geometry_reused_without_redraw(tmp_path, monkeypatch):
    import cartopy.crs as ccrs
    import geopandas as gpd
    from shapely.geometry import Polygon, LineString, MultiPoint
    from era5_fire.plotting import _plot_overlay, plt

    shape = tmp_path / "overlay.geojson"
    geometries = [
        Polygon([(0, 0), (3, 0), (3, 3), (0, 3)],
                holes=[[(1, 1), (2, 1), (2, 2), (1, 2)]]),
        LineString([(0, 0), (3, 3)]), MultiPoint([(1, 1), (2, 2)]),
    ]
    gdf = gpd.GeoDataFrame(geometry=geometries, crs="EPSG:4326").to_crs("EPSG:3857")
    gdf.to_file(shape)
    original_read = gpd.read_file
    reads = []

    def read_file(path):
        reads.append(path)
        return original_read(path)

    monkeypatch.setattr(gpd, "read_file", read_file)
    c = {"maps": {"overlay": {"path": shape, "weather": True}}}
    projection = ccrs.PlateCarree()
    fig, axes = plt.subplots(1, 2, subplot_kw={"projection": projection})

    def unexpected_draw(*args, **kwargs):
        pytest.fail("Adding an overlay must not redraw the figure")

    monkeypatch.setattr(fig.canvas, "draw_idle", unexpected_draw)
    try:
        for ax in axes:
            ax.set_extent([-1, 4, -1, 4], crs=projection)
            _plot_overlay(ax, c, (-1, 4, -1, 4), projection, "weather")
            assert len(ax.collections[0].get_segments()) == 3  # exterior, hole, line
            np.testing.assert_allclose(ax.collections[1].get_offsets(), [(1, 1), (2, 2)])
        assert len(reads) == 1
        # A different viewport reuses the reprojected source geometry too.
        assert _plot_overlay(axes[0], c, (10, 11, 10, 11), projection, "weather") is None
        assert len(reads) == 1
        # Editing the source invalidates both cached data and prepared coordinates.
        gdf.iloc[:1].to_file(shape)
        _plot_overlay(axes[0], c, (-1, 4, -1, 4), projection, "weather")
        assert len(reads) == 2
    finally:
        plt.close(fig)


def test_event_config(tmp_path):
    path = tmp_path / "event.yaml"
    config = {"start": "2023-07-24", "end": "2023-07-26", "mode": "point",
              "point": {"latitude": 38, "longitude": 13},
              "event": {"start": "2023-07-24T14:30+02:00", "end": "2023-07-25T12:45Z"}}
    path.write_text(yaml.safe_dump(config))
    c = load_config(path)
    assert c["event"]["start"] == pd.Timestamp("2023-07-24T12:30Z")
    assert c["start"] == pd.Timestamp("2023-07-24T00:00Z")
    for event in ({}, {"start": "bad"}, {"start": "2023-07-25", "end": "2023-07-24"}):
        config["event"] = event
        path.write_text(yaml.safe_dump(config))
        with pytest.raises(ValueError, match="event"):
            load_config(path)
    config["event"] = {"start": "2023-07-24T12:30"}
    path.write_text(yaml.safe_dump(config))
    assert load_config(path)["event"]["start"] == pd.Timestamp("2023-07-24T12:30Z")


@pytest.mark.parametrize("aligned", [False, True])
@pytest.mark.parametrize("start,end,lines,strip", [
    ("2023-07-24T02:30Z", "2023-07-24T16:45Z", 2, True),
    ("2023-07-24T02:30Z", None, 1, False),
    ("2023-07-23", "2023-07-25", 0, True),
    ("2023-07-22", "2023-07-23", 0, False),
])
def test_event_meteogram(aligned, start, end, lines, strip):
    from era5_fire.plotting import meteogram, plt
    ds = derive(data(pd.date_range("2023-07-24", periods=24, freq="h"))).isel(latitude=1, longitude=1)
    c = {"timezone": "Europe/Rome", "point": {"latitude": 38, "longitude": 13},
         "event": {"start": start, "end": end, "name": "Fire event"}}
    fig = meteogram(ds, c, aligned_maps=aligned)
    try:
        for ax in fig.axes[:4]:
            assert sum(line.get_gid() in ("event-start", "event-end") for line in ax.lines) == lines
        strips = [ax for ax in fig.axes if ax.get_label() == "event-strip"]
        assert bool(strips) == strip
        if strip:
            assert strips[0].get_xlim() == fig.axes[3].get_xlim()
            assert strips[0].get_position().y1 < fig.axes[3].get_position().y0
            assert strips[0].texts[0].get_text() == "Fire event"
        fig.canvas.draw()
        if strip:
            renderer = fig.canvas.get_renderer()
            assert fig.legends[0].get_window_extent(renderer).y1 < strips[0].get_window_extent(renderer).y0
    finally:
        plt.close(fig)
