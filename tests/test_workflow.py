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
