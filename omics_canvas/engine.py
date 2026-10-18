"""Graph model, validator and executor for the Omics Canvas plugin."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import cache as result_cache
from .catalog import Catalog, NodeSpec, load_catalog, safe_node_id
from .rbridge import run_python_task, run_task

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
DISPATCH_SCRIPT = PLUGIN_ROOT / "r" / "dispatch.R"
PY_DISPATCH_SCRIPT = PLUGIN_ROOT / "py" / "dispatch.py"
DEFAULT_RUNS_DIR = PLUGIN_ROOT / "runs"
DEFAULT_CACHE_DIR = PLUGIN_ROOT / ".cache" / "nodes"


class GraphError(ValueError):
    """Raised when a canvas graph is structurally invalid."""


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def slugify(value: str, fallback: str = "run") -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return slug[:48] or fallback


@dataclass
class Node:
    id: str
    type: str
    params: dict[str, Any] = field(default_factory=dict)
    x: float = 0.0
    y: float = 0.0
    label: str | None = None
    env: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {
            "id": self.id,
            "type": self.type,
            "params": self.params,
            "x": self.x,
            "y": self.y,
        }
        if self.label:
            data["label"] = self.label
        if self.env:
            data["env"] = self.env
        return data


@dataclass
class Edge:
    src: str
    src_port: str
    dst: str
    dst_port: str

    def to_dict(self) -> dict[str, str]:
        return {
            "from": self.src,
            "from_port": self.src_port,
            "to": self.dst,
            "to_port": self.dst_port,
        }


@dataclass
class Graph:
    name: str
    nodes: list[Node]
    edges: list[Edge]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Graph":
        if not isinstance(data, dict):
            raise GraphError("Graph must be a JSON object.")
        raw_nodes = data.get("nodes")
        if not isinstance(raw_nodes, list) or not raw_nodes:
            raise GraphError("Graph must contain a non-empty 'nodes' list.")
        nodes = [
            Node(
                id=str(n["id"]),
                type=str(n.get("type", n.get("node_type", ""))),
                params=dict(n.get("params") or {}),
                x=float(n.get("x", 0) or 0),
                y=float(n.get("y", 0) or 0),
                label=n.get("label"),
                env=n.get("env"),
            )
            for n in raw_nodes
        ]
        edges = []
        for e in data.get("edges", []) or []:
            edges.append(
                Edge(
                    src=str(e.get("from", e.get("source", ""))),
                    src_port=str(e.get("from_port", e.get("source_port", "out"))),
                    dst=str(e.get("to", e.get("target", ""))),
                    dst_port=str(e.get("to_port", e.get("target_port", "in"))),
                )
            )
        return cls(name=str(data.get("name") or "Untitled canvas"), nodes=nodes, edges=edges)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
        }

    def node(self, node_id: str) -> Node:
        for node in self.nodes:
            if node.id == node_id:
                return node
        raise GraphError(f"Unknown node id: {node_id}")

    def validate(self, catalog: Catalog) -> list[str]:
        errors: list[str] = []
        seen: set[str] = set()
        for node in self.nodes:
            if node.id in seen:
                errors.append(f"Duplicated node id: {node.id}")
            seen.add(node.id)
            if node.type not in catalog.nodes:
                errors.append(f"Node {node.id}: unknown type '{node.type}'")

        incoming: dict[tuple[str, str], int] = {}
        outgoing_nodes: dict[str, set[str]] = {n.id: set() for n in self.nodes}
        indegree: dict[str, int] = {n.id: 0 for n in self.nodes}

        for edge in self.edges:
            if edge.src not in seen:
                errors.append(f"Edge source does not exist: {edge.src}")
                continue
            if edge.dst not in seen:
                errors.append(f"Edge target does not exist: {edge.dst}")
                continue
            src_spec = catalog.nodes.get(self.node(edge.src).type)
            dst_spec = catalog.nodes.get(self.node(edge.dst).type)
            if src_spec is not None and src_spec.output(edge.src_port) is None:
                errors.append(
                    f"Node {edge.src}: unknown output port '{edge.src_port}'"
                )
            if dst_spec is not None and dst_spec.input(edge.dst_port) is None:
                errors.append(
                    f"Node {edge.dst}: unknown input port '{edge.dst_port}'"
                )
            if src_spec is not None and dst_spec is not None:
                src_port = src_spec.output(edge.src_port)
                dst_port = dst_spec.input(edge.dst_port)
                if (
                    src_port
                    and dst_port
                    and src_port.type != dst_port.type
                    and "any" not in (src_port.type, dst_port.type)
                ):
                    errors.append(
                        f"Edge {edge.src}.{edge.src_port} -> {edge.dst}.{edge.dst_port}: "
                        f"type mismatch ({src_port.type} vs {dst_port.type})"
                    )
            key = (edge.dst, edge.dst_port)
            incoming[key] = incoming.get(key, 0) + 1
            if incoming[key] > 1:
                errors.append(
                    f"Node {edge.dst}: input port '{edge.dst_port}' has multiple connections"
                )
            outgoing_nodes[edge.src].add(edge.dst)
            indegree[edge.dst] += 1

        for node in self.nodes:
            spec = catalog.nodes.get(node.type)
            if spec is None:
                continue
            for port in spec.inputs:
                if incoming.get((node.id, port.id), 0) == 0 and not _has_direct_source(
                    spec, port.id
                ):
                    errors.append(
                        f"Node {node.id} ({spec.title}): required input '{port.id}' is not connected"
                    )
            params = {**spec.defaults(), **node.params}
            for param in spec.params:
                if param.required and not _param_present(params.get(param.name)):
                    errors.append(
                        f"Node {node.id} ({spec.title}): required parameter "
                        f"'{param.name}' is missing"
                    )

        if not errors:
            order = self._topological_order(catalog)
            if order is None:
                errors.append("Graph contains a cycle; a canvas must be a DAG.")
        return errors

    def _topological_order(self, catalog: Catalog | None = None) -> list[str] | None:
        indegree = {n.id: 0 for n in self.nodes}
        adjacency: dict[str, list[str]] = {n.id: [] for n in self.nodes}
        for edge in self.edges:
            if edge.src in adjacency and edge.dst in indegree:
                adjacency[edge.src].append(edge.dst)
                indegree[edge.dst] += 1
        queue = sorted([node_id for node_id, deg in indegree.items() if deg == 0])
        order: list[str] = []
        while queue:
            current = queue.pop(0)
            order.append(current)
            for downstream in adjacency[current]:
                indegree[downstream] -= 1
                if indegree[downstream] == 0:
                    queue.append(downstream)
                    queue.sort()
        if len(order) != len(self.nodes):
            return None
        return order

    def execution_order(self, catalog: Catalog, targets: list[str] | None = None) -> list[str]:
        order = self._topological_order(catalog)
        if order is None:
            raise GraphError("Graph contains a cycle.")
        if not targets:
            return order
        unknown = [t for t in targets if t not in {n.id for n in self.nodes}]
        if unknown:
            raise GraphError(f"Unknown target node(s): {', '.join(unknown)}")
        needed: set[str] = set()
        stack = list(targets)
        while stack:
            current = stack.pop()
            if current in needed:
                continue
            needed.add(current)
            for edge in self.edges:
                if edge.dst == current:
                    stack.append(edge.src)
        return [node_id for node_id in order if node_id in needed]

    def incoming_edges(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.dst == node_id]


def _param_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (list, dict)):
        return len(value) > 0
    return True


def _has_direct_source(spec: NodeSpec, port_id: str) -> bool:
    """A port may also be filled by a parameter with the same name."""
    return any(param.name == port_id for param in spec.params)


def _coerce_param(param_type: str, value: Any) -> Any:
    if value is None:
        return None
    if param_type == "integer":
        return int(float(value))
    if param_type == "number":
        return float(value)
    if param_type == "boolean":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
    if param_type == "json":
        if isinstance(value, (dict, list)):
            return value
        return json.loads(value)
    return value if isinstance(value, str) else str(value)


def resolve_params(
    spec: NodeSpec,
    provided: dict[str, Any],
    workdir: Path,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for param in spec.params:
        raw = provided.get(param.name, None)
        if raw is None or (isinstance(raw, str) and raw.strip() == ""):
            if param.default is not None and not (
                isinstance(param.default, str) and param.default == ""
            ):
                out[param.name] = param.default
                continue
            if param.default is not None:
                out[param.name] = param.default
                continue
            if param.required:
                raise GraphError(
                    f"Node {spec.id}: required parameter '{param.name}' is missing"
                )
            continue
        value = _coerce_param(param.type, raw)
        if param.type == "file" and isinstance(value, str) and not os.path.isabs(value):
            value = str((workdir / value).resolve())
        out[param.name] = value
    return out


class Runner:
    def __init__(
        self,
        catalog: Catalog,
        runs_dir: str | Path = DEFAULT_RUNS_DIR,
        workdir: str | Path | None = None,
        env: str = "scptools",
        timeout: int = 3600,
        cache_dir: str | Path | None = None,
        use_cache: bool = True,
    ):
        self.catalog = catalog
        self.runs_dir = Path(runs_dir).resolve()
        self.workdir = Path(workdir or os.getcwd()).resolve()
        self.env = env
        self.timeout = timeout
        self.cache_dir = Path(cache_dir or DEFAULT_CACHE_DIR).resolve()
        self.use_cache = use_cache
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def new_run_dir(self, graph: Graph) -> tuple[str, Path]:
        base = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{slugify(graph.name)}"
        candidate = self.runs_dir / base
        counter = 1
        while candidate.exists():
            counter += 1
            candidate = self.runs_dir / f"{base}-{counter}"
        candidate.mkdir(parents=True, exist_ok=False)
        (candidate / "logs").mkdir(exist_ok=True)
        return candidate.name, candidate

    def run(
        self,
        graph: Graph,
        run_dir: str | Path,
        targets: list[str] | None = None,
        resume: bool = False,
        stop_on_error: bool = True,
        use_cache: bool | None = None,
    ) -> dict[str, Any]:
        # Pick up custom nodes and code overrides written since this Runner
        # was created.
        try:
            self.catalog = load_catalog(self.catalog.path)
        except Exception:  # noqa: BLE001 - keep the previous catalog on read errors
            pass
        effective_cache = self.use_cache if use_cache is None else bool(use_cache)
        wall_started = time.time()
        errors = graph.validate(self.catalog)
        if errors:
            raise GraphError("Invalid graph:\n- " + "\n- ".join(errors))

        run_dir = Path(run_dir).resolve()
        run_id = run_dir.name
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "logs").mkdir(exist_ok=True)
        (run_dir / "graph.json").write_text(
            json.dumps(graph.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )

        order = graph.execution_order(self.catalog, targets)
        manifest: dict[str, Any] = {
            "run_id": run_id,
            "run_dir": str(run_dir),
            "name": graph.name,
            "plugin": self.catalog.plugin,
            "status": "running",
            "started_at": now_iso(),
            "finished_at": None,
            "workdir": str(self.workdir),
            "order": order,
            "graph": graph.to_dict(),
            "nodes": {},
            "artifacts": {},
            "cache": {
                "enabled": effective_cache,
                "dir": str(self.cache_dir),
                "hits": 0,
                "misses": 0,
            },
        }
        for node in graph.nodes:
            spec = self.catalog.get(node.type)
            status = "pending" if node.id in order else "skipped"
            manifest["nodes"][node.id] = {
                "id": node.id,
                "type": node.type,
                "title": spec.title,
                "category": spec.category,
                "language": spec.language,
                "status": status,
                "params": node.params,
                "env": node.env or self.env,
                "position": {"x": node.x, "y": node.y},
                "started_at": None,
                "finished_at": None,
                "duration_s": None,
                "cache_hit": None,
                "cache_key": None,
                "artifacts": {},
                "metrics": {},
                "messages": [],
                "error": None,
                "log": f"logs/{node.id}.log",
            }
        manifest_path = run_dir / "manifest.json"
        if resume and manifest_path.exists():
            try:
                prior = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                prior = None
            if prior:
                if prior.get("started_at"):
                    manifest["started_at"] = prior["started_at"]
                for node_id, record in manifest["nodes"].items():
                    old = (prior.get("nodes") or {}).get(node_id)
                    if not old or old.get("status") != "success":
                        continue
                    record.update(
                        {
                            "status": "success",
                            "started_at": old.get("started_at"),
                            "finished_at": old.get("finished_at"),
                            "duration_s": old.get("duration_s"),
                            "cache_hit": old.get("cache_hit"),
                            "cache_key": old.get("cache_key"),
                            "artifacts": old.get("artifacts") or {},
                            "metrics": old.get("metrics") or {},
                            "messages": old.get("messages") or [],
                            "error": None,
                        }
                    )
                    Runner._merge_artifacts(manifest, node_id, record["artifacts"])
        _write_json_atomic(manifest_path, manifest)

        for node_id in order:
            node = graph.node(node_id)
            spec = self.catalog.get(node.type)
            record = manifest["nodes"][node_id]

            if resume and record.get("status") == "success":
                existing = record.get("artifacts") or {}
                if existing and all(
                    (run_dir / art["path"]).exists() for art in existing.values()
                ):
                    self._merge_artifacts(manifest, node_id, existing)
                    continue

            record["status"] = "running"
            record["started_at"] = now_iso()
            record["error"] = None
            _write_json_atomic(manifest_path, manifest)

            node_dir = run_dir / node_id
            node_dir.mkdir(parents=True, exist_ok=True)
            log_path = run_dir / "logs" / f"{node_id}.log"
            started = time.time()

            try:
                params = resolve_params(spec, node.params, self.workdir)
                inputs = self._collect_inputs(graph, manifest, run_dir, node_id)
                node_env = node.env or self.env
                task = {
                    "node": node_id,
                    "type": node.type,
                    "language": spec.language,
                    "r_function": spec.r_function,
                    "r_file": spec.r_file,
                    "py_file": str(PLUGIN_ROOT / "py" / spec.py_file) if spec.py_file else "",
                    "params": params,
                    "inputs": inputs,
                    "outdir": str(node_dir),
                    "run_id": run_id,
                    "workdir": str(self.workdir),
                    "env": node_env,
                }
                task_path = node_dir / "task.json"
                _write_json_atomic(task_path, task)

                cache_key = None
                node_env = node.env or self.env
                if effective_cache:
                    if spec.language == "python":
                        code_paths = [
                            PY_DISPATCH_SCRIPT,
                            PLUGIN_ROOT / "py" / "common.py",
                            PLUGIN_ROOT / "py" / spec.py_file,
                        ]
                    else:
                        code_paths = [
                            PLUGIN_ROOT / "r" / "common.R",
                            PLUGIN_ROOT / "r" / "dispatch.R",
                            PLUGIN_ROOT / "r" / spec.r_file,
                            PLUGIN_ROOT / "r" / "overrides" / f"{safe_node_id(node.type)}.R",
                        ]
                    cache_key = result_cache.compute_key(
                        node.type, params, inputs, code_paths, node_env
                    )
                    record["cache_key"] = cache_key
                    entry = result_cache.load_entry(self.cache_dir, cache_key)
                    if entry is not None:
                        restored = result_cache.restore_entry(
                            self.cache_dir, cache_key, entry, node_dir
                        )
                        result = {
                            "ok": True,
                            "artifacts": restored,
                            "metrics": entry.get("metrics") or {},
                            "messages": [
                                f"cache hit: reused {cache_key[:12]} (no process started)"
                            ],
                        }
                        _write_json_atomic(node_dir / "result.json", result)
                        artifacts = self._resolve_artifacts(
                            restored, node_dir, run_dir, run_id
                        )
                        record["artifacts"] = artifacts
                        self._merge_artifacts(manifest, node_id, artifacts)
                        record["metrics"] = result["metrics"]
                        record["messages"] = result["messages"]
                        record["cache_hit"] = True
                        record["status"] = "success"
                        manifest["cache"]["hits"] += 1
                        log_path.write_text(
                            f"cache hit: {cache_key}\nentry: {self.cache_dir / cache_key}\n",
                            encoding="utf-8",
                        )
                        continue

                if effective_cache:
                    manifest["cache"]["misses"] += 1

                if spec.language == "python":
                    proc = run_python_task(
                        PY_DISPATCH_SCRIPT,
                        task_path,
                        env=node_env,
                        timeout=self.timeout,
                    )
                else:
                    proc = run_task(
                        DISPATCH_SCRIPT,
                        task_path,
                        env=node_env,
                        timeout=self.timeout,
                    )
                log_text = _format_process_log(proc)
                log_path.write_text(log_text, encoding="utf-8")

                result_path = node_dir / "result.json"
                if proc.returncode != 0 and not result_path.exists():
                    raise RuntimeError(
                        f"R process failed with exit code {proc.returncode}.\n"
                        f"{_tail(log_text)}"
                    )
                if not result_path.exists():
                    raise RuntimeError(
                        f"R process did not write result.json.\n{_tail(log_text)}"
                    )
                result = json.loads(result_path.read_text(encoding="utf-8"))
                if not result.get("ok", False):
                    raise RuntimeError(result.get("error") or "R node reported failure.")

                artifacts = self._resolve_artifacts(
                    result.get("artifacts") or {}, node_dir, run_dir, run_id
                )
                record["artifacts"] = artifacts
                self._merge_artifacts(manifest, node_id, artifacts)
                record["metrics"] = result.get("metrics") or {}
                record["messages"] = result.get("messages") or []
                record["status"] = "success"
                record["cache_hit"] = False
                if effective_cache and cache_key:
                    result_cache.store_entry(
                        self.cache_dir,
                        cache_key,
                        node_dir,
                        artifacts,
                        record["metrics"],
                        record["messages"],
                        node.type,
                    )
            except subprocess.TimeoutExpired:
                record["status"] = "failed"
                record["error"] = f"Node timed out after {self.timeout} seconds."
            except Exception as exc:  # noqa: BLE001 - record every node failure
                record["status"] = "failed"
                record["error"] = str(exc)
                tb = traceback.format_exc()
                try:
                    log_path.write_text(
                        (log_path.read_text(encoding="utf-8") if log_path.exists() else "")
                        + "\n[engine]\n"
                        + tb,
                        encoding="utf-8",
                    )
                except OSError:
                    pass
            finally:
                record["finished_at"] = now_iso()
                record["duration_s"] = round(time.time() - started, 3)
                _write_json_atomic(manifest_path, manifest)

            if record["status"] == "failed" and stop_on_error:
                for later in order:
                    if manifest["nodes"][later]["status"] == "pending":
                        manifest["nodes"][later]["status"] = "skipped"
                break

        failed = any(n["status"] == "failed" for n in manifest["nodes"].values())
        manifest["status"] = "failed" if failed else "success"
        manifest["finished_at"] = now_iso()
        manifest["total_duration_s"] = round(
            sum(
                float(node.get("duration_s") or 0)
                for node in manifest["nodes"].values()
            ),
            3,
        )
        manifest["wall_duration_s"] = round(time.time() - wall_started, 3)
        slowest = max(
            (
                (node_id, float(record.get("duration_s") or 0))
                for node_id, record in manifest["nodes"].items()
            ),
            key=lambda item: item[1],
            default=(None, 0.0),
        )
        manifest["slowest_node"] = {"id": slowest[0], "duration_s": slowest[1]}
        _write_json_atomic(manifest_path, manifest)
        return manifest

    def _collect_inputs(
        self,
        graph: Graph,
        manifest: dict[str, Any],
        run_dir: Path,
        node_id: str,
    ) -> dict[str, str]:
        inputs: dict[str, str] = {}
        for edge in graph.incoming_edges(node_id):
            upstream = manifest["nodes"].get(edge.src)
            if upstream is None or upstream["status"] != "success":
                raise RuntimeError(
                    f"Upstream node {edge.src} did not complete successfully."
                )
            artifact = (upstream.get("artifacts") or {}).get(edge.src_port)
            if artifact is None:
                raise RuntimeError(
                    f"Upstream node {edge.src} has no artifact on port '{edge.src_port}'."
                )
            path = (run_dir / artifact["path"]).resolve()
            if not path.exists():
                raise RuntimeError(f"Input artifact is missing: {path}")
            inputs[edge.dst_port] = str(path)
        return inputs

    def _resolve_artifacts(
        self,
        artifacts: dict[str, Any],
        node_dir: Path,
        run_dir: Path,
        run_id: str,
    ) -> dict[str, Any]:
        resolved: dict[str, Any] = {}
        for port, artifact in artifacts.items():
            if not isinstance(artifact, dict):
                continue
            file_name = artifact.get("file")
            if not file_name:
                continue
            abs_path = (node_dir / file_name).resolve()
            if not abs_path.exists():
                continue
            rel = abs_path.relative_to(run_dir).as_posix()
            resolved[port] = {
                "port": port,
                "type": artifact.get("type", "file"),
                "label": artifact.get("label", port),
                "file": file_name,
                "path": rel,
                "abs_path": str(abs_path),
                "size_bytes": abs_path.stat().st_size,
                "url": f"api/runs/{run_id}/files/{rel}",
            }
        return resolved

    @staticmethod
    def _merge_artifacts(
        manifest: dict[str, Any], node_id: str, artifacts: dict[str, Any]
    ) -> None:
        for port, artifact in artifacts.items():
            manifest["artifacts"][f"{node_id}.{port}"] = artifact


def _format_process_log(proc: subprocess.CompletedProcess) -> str:
    parts = [f"$ exit_code={proc.returncode}"]
    if proc.stdout:
        parts.append("[stdout]\n" + proc.stdout)
    if proc.stderr:
        parts.append("[stderr]\n" + proc.stderr)
    return "\n".join(parts) + "\n"


def _tail(text: str, limit: int = 4000) -> str:
    return text if len(text) <= limit else "..." + text[-limit:]


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def load_run(run_dir: str | Path) -> dict[str, Any]:
    manifest_path = Path(run_dir) / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"No manifest in run directory: {run_dir}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def list_runs(runs_dir: str | Path = DEFAULT_RUNS_DIR) -> list[dict[str, Any]]:
    runs_dir = Path(runs_dir)
    if not runs_dir.exists():
        return []
    entries = []
    for child in sorted(runs_dir.iterdir(), reverse=True):
        manifest_path = child / "manifest.json"
        if child.is_dir() and manifest_path.exists():
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            entries.append(
                {
                    "run_id": data.get("run_id", child.name),
                    "name": data.get("name", child.name),
                    "status": data.get("status"),
                    "started_at": data.get("started_at"),
                    "finished_at": data.get("finished_at"),
                    "n_nodes": len(data.get("nodes", {})),
                }
            )
    return entries
