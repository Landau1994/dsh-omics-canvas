"""Small helpers available to Python nodes (``from common import ...``)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


def read_table(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(path, sep="\t")


def write_table(frame: pd.DataFrame, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, sep="\t", index=False)


def write_json(data: Any, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )


def artifact(outdir: str | Path, file: str, type: str = "table", label: str | None = None) -> dict:
    return {
        "file": file,
        "type": type,
        "label": label or file,
        "size_bytes": (Path(outdir) / file).stat().st_size
        if (Path(outdir) / file).exists()
        else None,
    }
