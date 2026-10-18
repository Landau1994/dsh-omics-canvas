"""Local HTTP server for the Omics Canvas editor and execution API."""

from __future__ import annotations

import json
import mimetypes
import re
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .catalog import (
    delete_custom_node,
    delete_node_code,
    load_catalog,
    read_node_code,
    upsert_custom_node,
    write_node_code,
)
from . import cache as result_cache
from .engine import (
    DEFAULT_RUNS_DIR,
    Graph,
    Runner,
    list_runs,
    now_iso,
)
from .report import build_bundle, report_html
from .rbridge import list_environments

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = PLUGIN_ROOT / "web"
EXAMPLES_DIR = Path(__file__).resolve().parent / "specs" / "examples"
CANVAS_DIR = PLUGIN_ROOT / "canvases"
CANVAS_LOCK = threading.Lock()


def _canvas_path(canvas_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", canvas_id):
        raise ValueError("Invalid canvas id")
    CANVAS_DIR.mkdir(parents=True, exist_ok=True)
    return CANVAS_DIR / f"{canvas_id}.json"


def load_canvas(canvas_id: str) -> dict:
    path = _canvas_path(canvas_id)
    if not path.exists():
        return {"canvas_id": canvas_id, "graph": None, "revision": 0}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"canvas_id": canvas_id, "graph": None, "revision": 0}


def save_canvas(canvas_id: str, graph: dict, revision: int | None = None,
                guard_seconds: float = 0) -> dict:
    existing = load_canvas(canvas_id)
    next_revision = int(revision) if revision is not None else int(existing.get("revision") or 0) + 1
    record = {
        "canvas_id": canvas_id,
        "graph": graph,
        "revision": next_revision,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "guard_until": time.time() + guard_seconds if guard_seconds > 0 else 0,
    }
    _canvas_path(canvas_id).write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return record


def apply_canvas_ops(graph: dict, ops: list[dict]) -> dict:
    """Apply a small, explicit patch vocabulary to a canvas graph."""
    import copy

    result = copy.deepcopy(graph or {})
    result.setdefault("nodes", [])
    result.setdefault("edges", [])
    nodes = {str(node.get("id")): node for node in result["nodes"]}
    for op in ops or []:
        kind = str(op.get("op") or op.get("type") or "")
        if kind == "set_node_params":
            node_id = str(op.get("node_id"))
            if node_id not in nodes:
                raise ValueError(f"Unknown node: {node_id}")
            params = op.get("params") or {}
            if op.get("replace"):
                nodes[node_id]["params"] = params
            else:
                nodes[node_id]["params"] = {**nodes[node_id].get("params", {}), **params}
        elif kind == "update_node":
            node_id = str(op.get("node_id"))
            if node_id not in nodes:
                raise ValueError(f"Unknown node: {node_id}")
            patch = op.get("patch") or {}
            for key in ("label", "env", "type"):
                if key in patch:
                    nodes[node_id][key] = patch[key]
        elif kind == "add_node":
            node = op.get("node") or {}
            node_id = str(node.get("id") or "")
            if not node_id or node_id in nodes:
                raise ValueError("add_node needs a unique node id")
            result["nodes"].append(node)
            nodes[node_id] = node
        elif kind == "remove_node":
            node_id = str(op.get("node_id"))
            result["nodes"] = [n for n in result["nodes"] if str(n.get("id")) != node_id]
            result["edges"] = [
                e for e in result["edges"]
                if str(e.get("from")) != node_id and str(e.get("to")) != node_id
            ]
            nodes.pop(node_id, None)
        elif kind == "add_edge":
            edge = op.get("edge") or {}
            if not edge.get("from") or not edge.get("to"):
                raise ValueError("add_edge needs from/to")
            result["edges"].append(edge)
        elif kind == "remove_edge":
            index = int(op.get("index", -1))
            if 0 <= index < len(result["edges"]):
                result["edges"].pop(index)
        else:
            raise ValueError(f"Unknown canvas operation: {kind}")
    return result



class CanvasState:
    def __init__(
        self,
        runs_dir: str | Path = DEFAULT_RUNS_DIR,
        workdir: str | Path | None = None,
        env: str = "scptools",
        timeout: int = 3600,
        use_cache: bool = True,
        cache_dir: str | Path | None = None,
    ):
        self.catalog = load_catalog()
        self.runner = Runner(
            self.catalog,
            runs_dir=runs_dir,
            workdir=workdir,
            env=env,
            timeout=timeout,
            cache_dir=cache_dir,
            use_cache=use_cache,
        )
        self.threads: dict[str, threading.Thread] = {}
        self.lock = threading.Lock()

    def reload_catalog(self) -> None:
        self.catalog = load_catalog()
        self.runner.catalog = self.catalog

    def examples(self) -> list[dict[str, str]]:
        if not EXAMPLES_DIR.exists():
            return []
        return [
            {"file": path.name, "name": path.stem.replace("_", " ")}
            for path in sorted(EXAMPLES_DIR.glob("*.json"))
        ]

    def start_run(self, graph: Graph) -> str:
        with self.lock:
            run_id, run_dir = self.runner.new_run_dir(graph)
        thread = threading.Thread(
            target=self._execute, args=(graph, run_dir), daemon=True, name=f"run-{run_id}"
        )
        self.threads[run_id] = thread
        thread.start()
        return run_id

    def _execute(self, graph: Graph, run_dir: Path) -> None:
        try:
            self.runner.run(graph, run_dir)
        except Exception as exc:  # noqa: BLE001 - surface failures to the UI
            manifest_path = run_dir / "manifest.json"
            if not manifest_path.exists():
                manifest_path.write_text(
                    json.dumps(
                        {
                            "run_id": run_dir.name,
                            "name": graph.name,
                            "status": "failed",
                            "error": str(exc),
                            "started_at": now_iso(),
                            "finished_at": now_iso(),
                            "graph": graph.to_dict(),
                            "nodes": {},
                            "artifacts": {},
                            "order": [],
                        },
                        indent=2,
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )


class CanvasHandler(BaseHTTPRequestHandler):
    server_version = "OmicsCanvas/0.1"
    protocol_version = "HTTP/1.1"

    @property
    def state(self) -> CanvasState:
        return self.server.state  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args) -> None:  # noqa: D102
        print(f"[server] {self.address_string()} {fmt % args}")

    def do_GET(self) -> None:  # noqa: N802
        path = unquote(urlparse(self.path).path)
        if path.startswith("/api/canvases/"):
            canvas_id = path[len("/api/canvases/"):]
            try:
                self._send_json(load_canvas(canvas_id))
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)
            return
        if path == "/api/environments":
            self._send_json({
                "environments": list_environments(),
                "default": self.state.runner.env,
                "python": self.state.runner.env,
            })
        elif path == "/api/cache":
            self._send_json(result_cache.stats(self.state.runner.cache_dir))
        elif path == "/api/catalog":
            self.state.reload_catalog()
            self._send_json({**self.state.catalog.to_dict(), "examples": self.state.examples()})
        elif path == "/api/custom-nodes":
            self.state.reload_catalog()
            self._send_json({
                "nodes": [
                    spec.to_dict()
                    for spec in self.state.catalog.nodes.values()
                    if spec.custom
                ]
            })
        elif path.startswith("/api/nodes/") and path.endswith("/code"):
            node_id = path[len("/api/nodes/"):-len("/code")]
            try:
                self.state.reload_catalog()
                self._send_json(read_node_code(self.state.catalog, unquote(node_id)))
            except (KeyError, ValueError) as exc:
                self._send_json({"error": str(exc)}, status=404)
        elif path == "/api/runs":
            self._send_json({"runs": list_runs(self.state.runner.runs_dir)})
        elif path.startswith("/api/runs/"):
            self._handle_run_get(path)
        elif path == "/api/examples":
            self._send_json({"examples": self.state.examples()})
        elif path.startswith("/api/examples/"):
            self._handle_example(path)
        else:
            self._serve_static(path)

    def do_POST(self) -> None:  # noqa: N802
        path = unquote(urlparse(self.path).path)
        try:
            body = self._read_json()
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json({"error": f"Invalid JSON: {exc}"}, status=400)
            return

        self.state.reload_catalog()
        if path == "/api/custom-nodes":
            try:
                entry = upsert_custom_node(body.get("node") or {}, body.get("code") or "")
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            self.state.reload_catalog()
            self._send_json({"node": entry, "catalog": self.state.catalog.to_dict()})
        elif path == "/api/validate":
            try:
                graph = Graph.from_dict(body.get("graph") or body)
            except Exception as exc:  # noqa: BLE001
                self._send_json({"valid": False, "errors": [str(exc)]})
                return
            errors = graph.validate(self.state.catalog)
            self._send_json({"valid": not errors, "errors": errors})
        elif path == "/api/run":
            try:
                graph = Graph.from_dict(body.get("graph") or body)
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": str(exc)}, status=400)
                return
            errors = graph.validate(self.state.catalog)
            if errors:
                self._send_json({"error": "Invalid graph", "errors": errors}, status=400)
                return
            run_id = self.state.start_run(graph)
            self._send_json({"run_id": run_id, "status": "running"})
        else:
            self._send_json({"error": "Not found"}, status=404)

    def do_PUT(self) -> None:  # noqa: N802
        path = unquote(urlparse(self.path).path)
        try:
            body = self._read_json()
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json({"error": f"Invalid JSON: {exc}"}, status=400)
            return
        if path.startswith("/api/canvases/"):
            canvas_id = path[len("/api/canvases/"):]
            try:
                self.state.reload_catalog()
                graph = body.get("graph") or {}
                with CANVAS_LOCK:
                    current = load_canvas(canvas_id)
                    if (
                        float(current.get("guard_until") or 0) > time.time()
                        and body.get("source") != "agent"
                    ):
                        self._send_json(
                            {"error": "agent update in progress", **current}, status=409
                        )
                        return
                    base_revision = body.get("base_revision")
                    if base_revision is not None and int(base_revision) != int(current.get("revision") or 0):
                        self._send_json(
                            {"error": "revision conflict", **current}, status=409
                        )
                        return
                    if graph.get("nodes"):
                        errors = Graph.from_dict(graph).validate(self.state.catalog)
                        if errors:
                            self._send_json({"error": "Invalid graph", "errors": errors}, status=400)
                            return
                    self._send_json(save_canvas(canvas_id, graph))
            except (ValueError, Exception) as exc:  # noqa: BLE001
                self._send_json({"error": str(exc)}, status=400)
            return
        if path.startswith("/api/nodes/") and path.endswith("/code"):
            node_id = path[len("/api/nodes/"):-len("/code")]
            try:
                self.state.reload_catalog()
                self._send_json(write_node_code(self.state.catalog, node_id, body.get("code") or ""))
            except (KeyError, ValueError) as exc:
                self._send_json({"error": str(exc)}, status=400)
            return
        self._send_json({"error": "Not found"}, status=404)

    def do_PATCH(self) -> None:  # noqa: N802
        path = unquote(urlparse(self.path).path)
        try:
            body = self._read_json()
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json({"error": f"Invalid JSON: {exc}"}, status=400)
            return
        if path.startswith("/api/canvases/"):
            canvas_id = path[len("/api/canvases/"):]
            try:
                self.state.reload_catalog()
                with CANVAS_LOCK:
                    current = load_canvas(canvas_id)
                    graph = current.get("graph") or {
                        "name": "Untitled canvas",
                        "nodes": [],
                        "edges": [],
                    }
                    graph = apply_canvas_ops(graph, body.get("ops") or [])
                    errors = Graph.from_dict(graph).validate(self.state.catalog)
                    if errors:
                        self._send_json({"error": "Invalid graph", "errors": errors}, status=400)
                        return
                    self._send_json(save_canvas(canvas_id, graph, guard_seconds=8))
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": str(exc)}, status=400)
            return
        self._send_json({"error": "Not found"}, status=404)

    def do_DELETE(self) -> None:  # noqa: N802
        path = unquote(urlparse(self.path).path)
        if path == "/api/cache":
            self._send_json(result_cache.clear(self.state.runner.cache_dir))
            return
        if path.startswith("/api/custom-nodes/"):
            node_id = path[len("/api/custom-nodes/"):]
            try:
                delete_custom_node(node_id)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            self.state.reload_catalog()
            self._send_json({"ok": True, "catalog": self.state.catalog.to_dict()})
            return
        if path.startswith("/api/nodes/") and path.endswith("/code"):
            node_id = path[len("/api/nodes/"):-len("/code")]
            try:
                self.state.reload_catalog()
                self._send_json(delete_node_code(self.state.catalog, node_id))
            except (KeyError, ValueError) as exc:
                self._send_json({"error": str(exc)}, status=400)
            return
        self._send_json({"error": "Not found"}, status=404)

    def _handle_run_get(self, path: str) -> None:
        parts = path[len("/api/runs/"):].split("/")
        run_id = parts[0]
        runs_root = Path(self.state.runner.runs_dir).resolve()
        run_dir = (runs_root / run_id).resolve()
        if run_dir != runs_root and runs_root not in run_dir.parents:
            self._send_json({"error": "Forbidden"}, status=403)
            return
        if not run_dir.exists():
            self._send_json({"error": "Run not found"}, status=404)
            return

        if len(parts) == 1:
            manifest_path = run_dir / "manifest.json"
            if not manifest_path.exists():
                self._send_json({"error": "Run manifest is not ready"}, status=404)
                return
            self._send_json(json.loads(manifest_path.read_text(encoding="utf-8")))
            return

        if parts[1] == "report":
            manifest_path = run_dir / "manifest.json"
            if not manifest_path.exists():
                self._send_json({"error": "Run manifest is not ready"}, status=404)
                return
            self._send_bytes(
                report_html(run_dir).encode("utf-8"),
                "text/html; charset=utf-8",
            )
            return

        if parts[1] == "export":
            manifest_path = run_dir / "manifest.json"
            if not manifest_path.exists():
                self._send_json({"error": "Run manifest is not ready"}, status=404)
                return
            self._send_bytes(
                build_bundle(run_dir),
                "application/zip",
                filename=f"{run_id}.zip",
            )
            return

        if parts[1] != "files" or len(parts) < 3:
            self._send_json({"error": "Not found"}, status=404)
            return
        rel = "/".join(parts[2:])
        target = (run_dir / rel).resolve()
        if run_dir not in target.parents:
            self._send_json({"error": "Forbidden"}, status=403)
            return
        if not target.is_file():
            self._send_json({"error": "File not found"}, status=404)
            return
        self._send_file(target)

    def _handle_example(self, path: str) -> None:
        name = path[len("/api/examples/"):]
        target = (EXAMPLES_DIR / name).resolve()
        if EXAMPLES_DIR.resolve() not in target.parents or not target.is_file():
            self._send_json({"error": "Example not found"}, status=404)
            return
        self._send_file(target)

    def _serve_static(self, path: str) -> None:
        if path in ("", "/"):
            path = "/index.html"
        web_root = WEB_DIR.resolve()
        target = (web_root / path.lstrip("/")).resolve()
        if web_root not in target.parents:
            self._send_json({"error": "Forbidden"}, status=403)
            return
        if not target.is_file():
            self._send_json({"error": "Not found"}, status=404)
            return
        self._send_file(target)

    def _send_file(self, target: Path) -> None:
        data = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if target.suffix == ".tsv":
            content_type = "text/tab-separated-values; charset=utf-8"
        elif target.suffix in {".js"}:
            content_type = "text/javascript; charset=utf-8"
        elif target.suffix in {".html"}:
            content_type = "text/html; charset=utf-8"
        elif target.suffix in {".css"}:
            content_type = "text/css; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_bytes(self, data: bytes, content_type: str, filename: str | None = None) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    runs_dir: str | Path = DEFAULT_RUNS_DIR,
    workdir: str | Path | None = None,
    env: str = "scptools",
    timeout: int = 3600,
    open_browser: bool = False,
    use_cache: bool = True,
    cache_dir: str | Path | None = None,
) -> None:
    state = CanvasState(
        runs_dir=runs_dir,
        workdir=workdir,
        env=env,
        timeout=timeout,
        use_cache=use_cache,
        cache_dir=cache_dir,
    )
    httpd = ThreadingHTTPServer((host, port), CanvasHandler)
    httpd.state = state  # type: ignore[attr-defined]
    url = f"http://{host}:{port}/"
    print(f"Omics Canvas running at {url}")
    print(f"Runs directory: {state.runner.runs_dir}")
    print(f"Work directory: {state.runner.workdir}")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        httpd.server_close()
