#!/usr/bin/env python3
"""Execute one Python Omics Canvas node.

Usage: python dispatch.py <task.json>

The node module is loaded from ``task["py_file"]`` and must define
``run(task)`` returning the same artifact contract as the R nodes:
``{"ok": True, "artifacts": {...}, "metrics": {...}, "messages": [...]}``.
The result is written to ``<outdir>/result.json`` so the Python engine can
collect it without parsing console output.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import traceback
from pathlib import Path

# Make the shared `common` helper importable from node modules.
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _write_result(outdir: Path, result: dict) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: dispatch.py <task.json>", file=sys.stderr)
        return 2
    task_path = Path(sys.argv[1])
    task = json.loads(task_path.read_text(encoding="utf-8"))
    outdir = Path(task["outdir"])
    py_file = task.get("py_file")
    result: dict
    try:
        if not py_file:
            raise ValueError("Task is missing 'py_file'.")
        module_path = Path(py_file)
        if not module_path.is_file():
            raise FileNotFoundError(f"Python node not found: {module_path}")
        spec = importlib.util.spec_from_file_location("omics_canvas_node", module_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load Python node: {module_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        function = getattr(module, task.get("r_function") or "run", None)
        if not callable(function):
            raise AttributeError(
                f"Node must define {task.get('r_function') or 'run'}(task)."
            )
        result = function(task)
        if not isinstance(result, dict):
            result = {"ok": True, "messages": [str(result)]}
        result.setdefault("ok", True)
    except Exception as exc:  # noqa: BLE001 - the dispatcher reports every failure
        result = {
            "ok": False,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
    result["node"] = task.get("node")
    _write_result(outdir, result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
