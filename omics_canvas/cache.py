"""Content-addressed cache for node results.

A node result is keyed by the node type, resolved parameters, the content of
its input artifacts, and the source files that implement it. A hit copies the
cached artifacts into the new run directory, so every run stays self-contained.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

CACHE_VERSION = "2"


def hash_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_key(
    node_type: str,
    params: dict[str, Any],
    inputs: dict[str, str],
    code_paths: list[str | Path],
    env: str,
) -> str:
    digest = hashlib.sha256()
    digest.update(CACHE_VERSION.encode())
    digest.update(node_type.encode())
    digest.update(json.dumps(params, sort_keys=True, default=str).encode())
    digest.update(env.encode())
    for port in sorted(inputs):
        digest.update(port.encode())
        digest.update(hash_file(inputs[port]).encode())
    for path in code_paths:
        candidate = Path(path)
        if candidate.exists():
            digest.update(hash_file(candidate).encode())
    return digest.hexdigest()


def entry_dir(cache_dir: str | Path, key: str) -> Path:
    return Path(cache_dir) / key


def load_entry(cache_dir: str | Path, key: str) -> dict[str, Any] | None:
    directory = entry_dir(cache_dir, key)
    meta_path = directory / "entry.json"
    if not meta_path.exists():
        return None
    try:
        entry = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    for artifact in (entry.get("artifacts") or {}).values():
        if not (directory / artifact.get("file", "")).is_file():
            return None
    return entry


def store_entry(
    cache_dir: str | Path,
    key: str,
    node_dir: str | Path,
    artifacts: dict[str, dict[str, Any]],
    metrics: dict[str, Any],
    messages: list[str],
    node_type: str,
) -> None:
    base = Path(cache_dir)
    base.mkdir(parents=True, exist_ok=True)
    target = entry_dir(base, key)
    staging = base / f".staging-{key}-{os.getpid()}"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        copied: dict[str, dict[str, Any]] = {}
        for port, artifact in artifacts.items():
            file_name = artifact.get("file")
            if not file_name:
                continue
            source = Path(node_dir) / file_name
            if not source.is_file():
                continue
            destination = staging / file_name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            copied[port] = {
                "file": file_name,
                "type": artifact.get("type", "file"),
                "label": artifact.get("label", port),
            }
        if not copied:
            return
        entry = {
            "cache_version": CACHE_VERSION,
            "key": key,
            "node_type": node_type,
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "artifacts": copied,
            "metrics": metrics,
            "messages": messages,
        }
        (staging / "entry.json").write_text(
            json.dumps(entry, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        os.replace(staging, target)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def restore_entry(
    cache_dir: str | Path,
    key: str,
    entry: dict[str, Any],
    node_dir: str | Path,
) -> dict[str, dict[str, Any]]:
    source_dir = entry_dir(cache_dir, key)
    target_dir = Path(node_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, dict[str, Any]] = {}
    for port, artifact in (entry.get("artifacts") or {}).items():
        source = source_dir / artifact["file"]
        destination = target_dir / artifact["file"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        artifacts[port] = {
            "file": artifact["file"],
            "type": artifact.get("type", "file"),
            "label": artifact.get("label", port),
        }
    return artifacts


def stats(cache_dir: str | Path) -> dict[str, Any]:
    base = Path(cache_dir)
    entries = 0
    size = 0
    if base.exists():
        for child in base.iterdir():
            if not child.is_dir() or child.name.startswith("."):
                continue
            if (child / "entry.json").exists():
                entries += 1
                for path in child.rglob("*"):
                    if path.is_file():
                        size += path.stat().st_size
    return {"dir": str(base), "entries": entries, "size_bytes": size}


def clear(cache_dir: str | Path) -> dict[str, Any]:
    base = Path(cache_dir)
    before = stats(base)
    if base.exists():
        for child in base.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                try:
                    child.unlink()
                except OSError:
                    pass
    return {"before": before, "after": stats(base)}
