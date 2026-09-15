"""Runtime settings. Everything configurable comes from environment variables so the
same code runs unchanged on a laptop, inside the Docker ingestion container, and in CI.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Research starts in 2005. Ingestion starts one year earlier so that 252-trading-day
# lookbacks (e.g. 12-month momentum) are already warm on the first research date.
DEFAULT_START = "2004-01-01"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    default_start: str

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"


def load_settings() -> Settings:
    return Settings(
        data_dir=Path(os.environ.get("MSL_DATA_DIR", "data")).resolve(),
        default_start=os.environ.get("MSL_DEFAULT_START", DEFAULT_START),
    )
