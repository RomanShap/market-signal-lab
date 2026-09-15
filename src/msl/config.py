"""Runtime settings. Everything configurable comes from environment variables so the
same code runs unchanged on a laptop, inside the Docker ingestion container, and in CI.

A ``.env`` file in the working directory is read on start-up **without overriding**
variables that are already set — so `docker compose` (which injects ``.env`` itself) and a
bare ``uv run msl`` see the same configuration. ``.env`` is git-ignored; secrets such as
``DATABRICKS_TOKEN`` live only there or in the real environment, never in code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Research starts in 2005. Ingestion starts one year earlier so that 252-trading-day
# lookbacks (e.g. 12-month momentum) are already warm on the first research date.
DEFAULT_START = "2004-01-01"


def load_dotenv(path: Path = Path(".env")) -> int:
    """Minimal ``KEY=VALUE`` loader (comments and blank lines ignored, optional quotes
    stripped). Returns the number of variables set. Deliberately tiny — no dependency."""
    if not path.is_file():
        return 0
    loaded = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip("'\"")
        if key and key not in os.environ and value:
            os.environ[key] = value
            loaded += 1
    return loaded


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    default_start: str

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        data_dir=Path(os.environ.get("MSL_DATA_DIR", "data")).resolve(),
        default_start=os.environ.get("MSL_DEFAULT_START", DEFAULT_START),
    )
