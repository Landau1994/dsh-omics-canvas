"""Bridge between the Python graph engine and the R analysis nodes."""

from __future__ import annotations

import functools
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_ENV = os.environ.get("OMICS_CANVAS_ENV", "scptools")


class RBridgeError(RuntimeError):
    pass


def _find_conda() -> str | None:
    conda = shutil.which("conda")
    if conda is not None:
        return conda
    for candidate in ("~/anaconda3/bin/conda", "~/miniconda3/bin/conda"):
        expanded = os.path.expanduser(candidate)
        if os.path.exists(expanded):
            return expanded
    return None


@functools.lru_cache(maxsize=16)
def _conda_which(env: str, executable: str) -> str | None:
    conda = _find_conda()
    if conda is None:
        return None
    try:
        result = subprocess.run(
            [conda, "run", "-n", env, "which", executable],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if result.returncode == 0 and lines:
            candidate = lines[-1]
            if os.path.exists(candidate):
                return candidate
    except (OSError, subprocess.SubprocessError):
        pass
    return None


@functools.lru_cache(maxsize=4)
def resolve_rscript(env: str = DEFAULT_ENV) -> str:
    """Resolve Rscript from the requested conda environment."""
    override = os.environ.get("OMICS_CANVAS_RSCRIPT")
    if override:
        if not os.path.exists(override):
            raise RBridgeError(f"OMICS_CANVAS_RSCRIPT does not exist: {override}")
        return override

    candidate = _conda_which(env, "Rscript")
    if candidate:
        return candidate

    candidate = shutil.which("Rscript")
    if candidate:
        return candidate

    raise RBridgeError(
        "Could not find Rscript. Activate the conda environment or set "
        "OMICS_CANVAS_RSCRIPT to the Rscript binary."
    )


@functools.lru_cache(maxsize=4)
def resolve_python(env: str = DEFAULT_ENV) -> str:
    """Resolve the Python interpreter from the requested conda environment."""
    override = os.environ.get("OMICS_CANVAS_PYTHON")
    if override:
        if not os.path.exists(override):
            raise RBridgeError(f"OMICS_CANVAS_PYTHON does not exist: {override}")
        return override

    candidate = _conda_which(env, "python")
    if candidate:
        return candidate

    if sys.executable:
        return sys.executable
    candidate = shutil.which("python3")
    if candidate:
        return candidate
    raise RBridgeError(
        "Could not find a Python interpreter for Python nodes. "
        "Set OMICS_CANVAS_PYTHON to the interpreter to use."
    )


def run_task(
    dispatch_script: str | Path,
    task_path: str | Path,
    env: str = DEFAULT_ENV,
    timeout: int = 3600,
) -> subprocess.CompletedProcess:
    rscript = resolve_rscript(env)
    return subprocess.run(
        [rscript, "--vanilla", str(dispatch_script), str(task_path)],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env={**os.environ, "MPLCONFIGDIR": os.environ.get("MPLCONFIGDIR", "/tmp/omics-canvas-mpl")},
    )


def run_python_task(
    dispatch_script: str | Path,
    task_path: str | Path,
    env: str = DEFAULT_ENV,
    timeout: int = 3600,
) -> subprocess.CompletedProcess:
    python = resolve_python(env)
    plugin_root = Path(dispatch_script).resolve().parent.parent
    python_path = os.pathsep.join(
        part for part in (str(plugin_root), os.environ.get("PYTHONPATH", "")) if part
    )
    return subprocess.run(
        [python, str(dispatch_script), str(task_path)],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env={
            **os.environ,
            "PYTHONPATH": python_path,
            "MPLCONFIGDIR": os.environ.get("MPLCONFIGDIR", "/tmp/omics-canvas-mpl"),
        },
    )


@functools.lru_cache(maxsize=1)
def list_environments() -> list[str]:
    """List conda environment names, falling back to the envs directory."""
    names: list[str] = []
    conda = _find_conda()
    if conda is not None:
        try:
            result = subprocess.run(
                [conda, "env", "list", "--json"],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                for path in data.get("envs") or []:
                    names.append(Path(path).name)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            names = []
    if not names:
        for root in (Path.home() / "anaconda3" / "envs", Path.home() / "miniconda3" / "envs"):
            if root.is_dir():
                names.extend(child.name for child in root.iterdir() if child.is_dir())
    names = sorted({name for name in names if name})
    return names
