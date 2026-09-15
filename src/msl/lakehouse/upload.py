"""The ingestion -> Databricks handoff: mirror the raw landing zone into a Unity Catalog
Volume, preserving the Hive layout so Spark reads ``provider`` / ``pull_id`` as columns.

    data/raw/prices/provider=yfinance/pull_id=…/AAPL.parquet
      -> /Volumes/<catalog>/<schema>/<volume>/raw/prices/provider=yfinance/pull_id=…/AAPL.parquet

Idempotent: a file whose remote copy already has the same size is skipped, so re-running
after a partial failure — or after an incremental pull — only moves what is new.
Free Edition has no external cloud storage, which is why the Files API (not S3/ADLS)
is the transport; see ADR-0004.

Authentication (resolved in this order, all standard Databricks SDK mechanisms):
  1. ``DATABRICKS_HOST`` + ``DATABRICKS_TOKEN`` in the environment / ``.env``  — the
     container path;
  2. otherwise ``DATABRICKS_HOST`` alone -> browser-based OAuth (user-to-machine), which
     Free Edition supports; the SDK caches the token under ``~/.databricks/``.
The code never sees, logs or stores a token itself.
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Protocol

log = logging.getLogger(__name__)

DEFAULT_VOLUME = "/Volumes/workspace/default/raw"  # Free Edition's default catalog + schema


class VolumeFiles(Protocol):
    """The three Files-API calls the sync needs — kept tiny so tests can fake it."""

    def remote_size(self, path: str) -> int | None: ...  # None when the file does not exist
    def mkdir(self, path: str) -> None: ...
    def upload(self, path: str, contents: BinaryIO) -> None: ...


@dataclass
class SyncPlan:
    to_upload: list[tuple[Path, str]] = field(default_factory=list)  # (local, remote)
    skipped: int = 0
    directories: set[str] = field(default_factory=set)


def plan_sync(raw_dir: Path, volume_root: str, files: VolumeFiles) -> SyncPlan:
    """Decide what to move. Pure planning, no uploads."""
    plan = SyncPlan()
    for local in sorted(p for p in raw_dir.rglob("*") if p.is_file()):
        remote = f"{volume_root}/raw/{local.relative_to(raw_dir).as_posix()}"
        if files.remote_size(remote) == local.stat().st_size:
            plan.skipped += 1
            continue
        plan.to_upload.append((local, remote))
        plan.directories.add(remote.rsplit("/", 1)[0])
    return plan


def run_sync(plan: SyncPlan, files: VolumeFiles, workers: int = 8) -> int:
    """Create directories, then upload in parallel. Returns the number of files moved."""
    for d in sorted(plan.directories):  # shortest first -> parents before children
        files.mkdir(d)

    def _one(pair: tuple[Path, str]) -> None:
        local, remote = pair
        with local.open("rb") as fh:
            files.upload(remote, fh)
        log.debug("uploaded %s", remote)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(_one, plan.to_upload))
    return len(plan.to_upload)


# ---------------------------------------------------------------- Databricks-backed impl


class DatabricksVolumeFiles:
    """`VolumeFiles` over the real Files API."""

    def __init__(self, client) -> None:  # noqa: ANN001 - WorkspaceClient, imported lazily
        self._files = client.files

    def remote_size(self, path: str) -> int | None:
        from databricks.sdk.errors import NotFound

        try:
            return self._files.get_metadata(path).content_length
        except NotFound:
            return None

    def mkdir(self, path: str) -> None:
        self._files.create_directory(path)  # idempotent on the server side

    def upload(self, path: str, contents: BinaryIO) -> None:
        self._files.upload(path, contents, overwrite=True)


def connect(host: str | None = None):
    """A WorkspaceClient using token auth when a token is present, browser OAuth otherwise."""
    from databricks.sdk import WorkspaceClient

    host = host or os.environ.get("DATABRICKS_HOST")
    if os.environ.get("DATABRICKS_TOKEN"):
        return WorkspaceClient(host=host)  # host+token picked up from the environment
    if not host:
        raise SystemExit(
            "set DATABRICKS_HOST (and DATABRICKS_TOKEN, or sign in through the browser) — "
            "see .env.example"
        )
    log.info("no DATABRICKS_TOKEN set — opening the browser for OAuth sign-in to %s", host)
    return WorkspaceClient(host=host, auth_type="external-browser")


def ensure_volume(client, volume_root: str) -> None:  # noqa: ANN001
    """Create the managed volume behind ``/Volumes/<catalog>/<schema>/<volume>`` if absent."""
    from databricks.sdk.errors import NotFound
    from databricks.sdk.service.catalog import VolumeType

    parts = volume_root.strip("/").split("/")
    if len(parts) != 4 or parts[0] != "Volumes":
        raise ValueError(f"expected /Volumes/<catalog>/<schema>/<volume>, got {volume_root!r}")
    _, catalog, schema, name = parts
    try:
        client.volumes.read(f"{catalog}.{schema}.{name}")
    except NotFound:
        log.info("creating managed volume %s.%s.%s", catalog, schema, name)
        client.volumes.create(catalog, schema, name, VolumeType.MANAGED)


def check(client) -> str:  # noqa: ANN001
    """Prove the connection works and say who we are."""
    me = client.current_user.me()
    return f"connected to {client.config.host} as {me.user_name}"
