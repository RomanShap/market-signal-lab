"""Volume sync planning against an in-memory fake of the Files API — no Databricks needed."""

from io import BytesIO

from msl.lakehouse.upload import plan_sync, run_sync


class FakeVolume:
    def __init__(self, existing: dict[str, int] | None = None):
        self.files: dict[str, bytes] = {}
        self.sizes: dict[str, int] = dict(existing or {})
        self.dirs: list[str] = []

    def remote_size(self, path):
        return self.sizes.get(path)

    def mkdir(self, path):
        self.dirs.append(path)

    def upload(self, path, contents):
        data = contents.read()
        self.files[path] = data
        self.sizes[path] = len(data)


def _landing_zone(tmp_path):
    raw = tmp_path / "raw"
    a = raw / "prices" / "provider=yfinance" / "pull_id=p1" / "AAPL.parquet"
    b = raw / "reference" / "sp500_constituents" / "provider=wikipedia" / "pull_id=p1" / "c.parquet"
    for p, payload in ((a, b"x" * 10), (b, b"y" * 20)):
        p.parent.mkdir(parents=True)
        p.write_bytes(payload)
    return raw, a, b


def test_plan_preserves_hive_layout_under_volume_root(tmp_path):
    raw, a, b = _landing_zone(tmp_path)
    plan = plan_sync(raw, "/Volumes/workspace/default/raw", FakeVolume())
    remotes = [r for _, r in plan.to_upload]
    assert remotes == [
        "/Volumes/workspace/default/raw/raw/prices/provider=yfinance/pull_id=p1/AAPL.parquet",
        "/Volumes/workspace/default/raw/raw/reference/sp500_constituents/provider=wikipedia/pull_id=p1/c.parquet",
    ]
    assert plan.skipped == 0
    assert (
        "/Volumes/workspace/default/raw/raw/prices/provider=yfinance/pull_id=p1" in plan.directories
    )


def test_same_size_remote_file_is_skipped_and_changed_one_is_not(tmp_path):
    raw, a, b = _landing_zone(tmp_path)
    root = "/Volumes/workspace/default/raw"
    existing = {
        f"{root}/raw/prices/provider=yfinance/pull_id=p1/AAPL.parquet": 10,  # identical size
        f"{root}/raw/reference/sp500_constituents/provider=wikipedia/pull_id=p1/c.parquet": 5,
    }
    plan = plan_sync(raw, root, FakeVolume(existing))
    assert plan.skipped == 1
    assert [loc.name for loc, _ in plan.to_upload] == ["c.parquet"]


def test_run_sync_creates_dirs_then_uploads_bytes(tmp_path):
    raw, a, b = _landing_zone(tmp_path)
    vol = FakeVolume()
    plan = plan_sync(raw, "/Volumes/workspace/default/raw", vol)
    moved = run_sync(plan, vol, workers=2)
    assert moved == 2
    assert len(vol.dirs) == 2 and vol.dirs == sorted(vol.dirs)
    assert (
        vol.files[
            "/Volumes/workspace/default/raw/raw/prices/provider=yfinance/pull_id=p1/AAPL.parquet"
        ]
        == b"x" * 10
    )
    # second run is a no-op
    again = plan_sync(raw, "/Volumes/workspace/default/raw", vol)
    assert again.to_upload == [] and again.skipped == 2


def test_fake_volume_upload_reads_stream():
    vol = FakeVolume()
    vol.upload("/Volumes/x/y/z/f", BytesIO(b"abc"))
    assert vol.remote_size("/Volumes/x/y/z/f") == 3
