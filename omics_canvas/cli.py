"""Command line interface for the Omics Canvas plugin."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .catalog import load_catalog
from .engine import (
    DEFAULT_CACHE_DIR,
    DEFAULT_RUNS_DIR,
    Graph,
    GraphError,
    Runner,
    list_runs,
    load_run,
)
from . import cache as result_cache
from .report import build_bundle, report_html


def _read_graph(path: str) -> Graph:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Graph.from_dict(data)


def cmd_list(args: argparse.Namespace) -> int:
    catalog = load_catalog()
    print(f"{catalog.plugin.get('name', 'Omics Canvas')} "
          f"v{catalog.plugin.get('version', '?')} "
          f"(env: {catalog.plugin.get('environment', 'scptools')})")
    for category in catalog.categories:
        nodes = [n for n in catalog.nodes.values() if n.category == category["id"]]
        print(f"\n[{category['label']}] ({len(nodes)} nodes)")
        for spec in nodes:
            print(f"  {spec.id:24s} {spec.title}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    catalog = load_catalog()
    graph = _read_graph(args.graph)
    errors = graph.validate(catalog)
    if errors:
        print("Invalid graph:")
        for error in errors:
            print("  -", error)
        return 1
    order = graph.execution_order(catalog, args.target)
    print(f"Valid graph: {graph.name}")
    print("Execution order:", " -> ".join(order))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    catalog = load_catalog()
    graph = _read_graph(args.graph)
    runner = Runner(
        catalog,
        runs_dir=args.runs_dir,
        workdir=args.workdir,
        env=args.env,
        timeout=args.timeout,
        cache_dir=args.cache_dir,
        use_cache=not args.no_cache,
    )
    if args.run_dir:
        run_dir = Path(args.run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
    else:
        _, run_dir = runner.new_run_dir(graph)

    print(f"Run directory: {run_dir}")
    try:
        manifest = runner.run(
            graph,
            run_dir,
            targets=args.target,
            resume=args.resume,
            stop_on_error=not args.keep_going,
            use_cache=not args.no_cache,
        )
    except GraphError as exc:
        print(exc, file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
    else:
        _print_summary(manifest)
    return 0 if manifest["status"] == "success" else 1


def _print_summary(manifest: dict) -> None:
    print(f"\n{manifest['name']} -- {manifest['status']}")
    for node_id in manifest.get("order", []):
        node = manifest["nodes"][node_id]
        icon = {"success": "OK", "failed": "FAIL", "skipped": "SKIP",
                "pending": "...", "running": "..."}.get(node["status"], "?")
        print(f"  [{icon:4s}] {node_id:18s} {node['title']} "
              f"({node.get('duration_s') or 0:.2f}s)")
        if node.get("error"):
            print(f"         error: {node['error'].splitlines()[0]}")
        for port, artifact in (node.get("artifacts") or {}).items():
            print(f"         {port}: {artifact['path']}")
    if manifest.get("status") != "success":
        print("\nInspect logs under:", manifest.get("run_dir") or "(run directory)")


def cmd_serve(args: argparse.Namespace) -> int:
    from .server import serve

    serve(
        host=args.host,
        port=args.port,
        runs_dir=args.runs_dir,
        workdir=args.workdir,
        env=args.env,
        timeout=args.timeout,
        open_browser=args.open,
        use_cache=not args.no_cache,
        cache_dir=args.cache_dir,
    )
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    run_dir = Path(args.runs_dir) / args.run_id
    if not (run_dir / "manifest.json").exists():
        print(f"Run not found: {run_dir}", file=sys.stderr)
        return 1
    if args.format == "html":
        data = report_html(run_dir).encode("utf-8")
        suffix = ".html"
    else:
        data = build_bundle(run_dir)
        suffix = ".zip"
    output = Path(args.out) if args.out else run_dir / f"{args.run_id}{suffix}"
    output.write_bytes(data)
    print(output)
    return 0


def cmd_cache(args: argparse.Namespace) -> int:
    if args.action == "clear":
        result = result_cache.clear(args.cache_dir)
        print(f"Cleared {result['before']['entries']} entries "
              f"({result['before']['size_bytes']} bytes) from {result['before']['dir']}")
        return 0
    stats = result_cache.stats(args.cache_dir)
    print(f"{stats['entries']} entries · {stats['size_bytes']} bytes · {stats['dir']}")
    return 0


def cmd_runs(args: argparse.Namespace) -> int:
    entries = list_runs(args.runs_dir)
    if not entries:
        print("No runs yet.")
        return 0
    for entry in entries:
        print(f"{entry['run_id']:40s} {entry['status']:8s} {entry['name']}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    manifest = load_run(Path(args.runs_dir) / args.run_id)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="omics-canvas",
        description="Canvas-style node engine for bulk RNA-seq and proteomics.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="List the node catalog.")
    p_list.set_defaults(func=cmd_list)

    p_validate = sub.add_parser("validate", help="Validate a canvas graph JSON.")
    p_validate.add_argument("graph")
    p_validate.add_argument("--target", nargs="+", default=None)
    p_validate.set_defaults(func=cmd_validate)

    p_run = sub.add_parser("run", help="Execute a canvas graph.")
    p_run.add_argument("graph")
    p_run.add_argument("--run-dir", default=None)
    p_run.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR))
    p_run.add_argument("--workdir", default=None,
                       help="Base directory for relative file parameters.")
    p_run.add_argument("--env", default="scptools", help="Conda environment.")
    p_run.add_argument("--timeout", type=int, default=3600,
                       help="Per-node timeout in seconds.")
    p_run.add_argument("--target", nargs="+", default=None,
                       help="Only run ancestors of these node ids.")
    p_run.add_argument("--resume", action="store_true")
    p_run.add_argument("--no-cache", action="store_true",
                       help="Ignore the content-addressed result cache.")
    p_run.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    p_run.add_argument("--keep-going", action="store_true",
                       help="Continue downstream nodes after a failure.")
    p_run.add_argument("--json", action="store_true", help="Print the full manifest.")
    p_run.set_defaults(func=cmd_run)

    p_serve = sub.add_parser("serve", help="Serve the canvas editor and run API.")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8765)
    p_serve.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR))
    p_serve.add_argument("--workdir", default=None)
    p_serve.add_argument("--env", default="scptools")
    p_serve.add_argument("--timeout", type=int, default=3600)
    p_serve.add_argument("--open", action="store_true")
    p_serve.add_argument("--no-cache", action="store_true")
    p_serve.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    p_serve.set_defaults(func=cmd_serve)

    p_export = sub.add_parser("export", help="Write an HTML report or a reproducible bundle.")
    p_export.add_argument("run_id")
    p_export.add_argument("--format", choices=["html", "bundle"], default="html")
    p_export.add_argument("--out", default=None)
    p_export.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR))
    p_export.set_defaults(func=cmd_export)

    p_cache = sub.add_parser("cache", help="Inspect or clear the node result cache.")
    p_cache.add_argument("action", choices=["stats", "clear"], nargs="?", default="stats")
    p_cache.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    p_cache.set_defaults(func=cmd_cache)

    p_runs = sub.add_parser("runs", help="List past runs.")
    p_runs.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR))
    p_runs.set_defaults(func=cmd_runs)

    p_show = sub.add_parser("show", help="Print a run manifest.")
    p_show.add_argument("run_id")
    p_show.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR))
    p_show.set_defaults(func=cmd_show)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
