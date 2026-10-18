"""Publication-friendly HTML reports and reproducible run bundles."""

from __future__ import annotations

import base64
import html
import io
import json
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
R_DIR = PLUGIN_ROOT / "r"

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".svg", ".webp"}


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _table(rows: list[list[Any]], header: list[str]) -> str:
    if not rows:
        return "<p class='muted'>No rows.</p>"
    head = "".join(f"<th>{_esc(cell)}</th>" for cell in header)
    body = "".join(
        "<tr>" + "".join(f"<td>{_esc(cell)}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _preview_table(path: Path, limit: int = 12) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "<p class='muted'>Table could not be read.</p>"
    if not lines:
        return "<p class='muted'>Empty table.</p>"
    header = lines[0].split("\t")
    rows = [line.split("\t") for line in lines[1:limit + 1]]
    preview = _table(rows, header)
    if len(lines) - 1 > limit:
        preview += f"<p class='muted'>Preview of {limit} rows; the bundle contains the full table.</p>"
    return preview


def _artifact_html(run_dir: Path, artifact: dict[str, Any]) -> str:
    path = run_dir / artifact.get("path", "")
    label = _esc(artifact.get("label") or artifact.get("port") or path.name)
    name = path.name
    size = artifact.get("size_bytes")
    size_text = f"{size / 1024:.1f} KB" if isinstance(size, (int, float)) else ""
    if not path.is_file():
        return f"<div class='artifact'><b>{label}</b> <span class='muted'>(missing)</span></div>"
    suffix = path.suffix.lower()
    body = ""
    if suffix in IMAGE_SUFFIXES:
        mime = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".svg": "image/svg+xml", ".webp": "image/webp",
        }.get(suffix, "application/octet-stream")
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        body = f"<img alt='{label}' src='data:{mime};base64,{data}'/>"
    elif suffix in {".tsv", ".csv", ".txt"}:
        if suffix == ".csv":
            body = _preview_table(path)
        else:
            body = _preview_table(path)
    elif suffix == ".pdf":
        body = f"<p class='muted'>PDF artifact: {_esc(name)} ({size_text})</p>"
    else:
        body = f"<p class='muted'>{_esc(name)} ({size_text})</p>"
    return (
        f"<div class='artifact'><div class='artifact-head'><b>{label}</b>"
        f"<span class='muted'>{_esc(name)} {size_text}</span></div>{body}</div>"
    )


def _node_section(run_dir: Path, node: dict[str, Any]) -> str:
    artifacts = node.get("artifacts") or {}
    params = node.get("params") or {}
    metrics = node.get("metrics") or {}
    messages = node.get("messages") or []
    bits = [
        f"<section class='node'><h3>{_esc(node.get('title') or node.get('id'))}"
        f" <span class='pill'>{_esc(node.get('status'))}</span></h3>",
        f"<div class='meta'><code>{_esc(node.get('type'))}</code> · "
        f"{_esc(node.get('language') or 'r')} · env {_esc(node.get('env') or '')} · "
        f"{_esc(node.get('duration_s') or 0)} s"
        + (" · <span class='cache'>cached</span>" if node.get("cache_hit") else "")
        + "</div>",
    ]
    if params:
        rows = [[k, json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v]
                for k, v in params.items()]
        bits.append("<h4>Parameters</h4>" + _table(rows, ["name", "value"]))
    if metrics:
        rows = [[k, json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v]
                for k, v in metrics.items()]
        bits.append("<h4>Metrics</h4>" + _table(rows, ["metric", "value"]))
    if messages:
        bits.append("<h4>Messages</h4><ul>" + "".join(f"<li>{_esc(m)}</li>" for m in messages) + "</ul>")
    if artifacts:
        bits.append("<h4>Outputs</h4>")
        for artifact in artifacts.values():
            bits.append(_artifact_html(run_dir, artifact))
    bits.append("</section>")
    return "\n".join(bits)


def graph_svg(graph: dict[str, Any]) -> str:
    """Render the canvas DAG as a self-contained SVG for the report."""
    nodes = [node for node in (graph.get("nodes") or []) if node.get("id")]
    if not nodes:
        return ""
    edges = [edge for edge in (graph.get("edges") or []) if edge.get("from") and edge.get("to")]
    positions = {
        str(node["id"]): (float(node.get("x", 0) or 0), float(node.get("y", 0) or 0))
        for node in nodes
    }
    min_x = min(value[0] for value in positions.values())
    min_y = min(value[1] for value in positions.values())
    max_x = max(value[0] for value in positions.values())
    max_y = max(value[1] for value in positions.values())
    if max_x == min_x and max_y == min_y:
        # Stored coordinates are absent; lay the nodes out in one row.
        for index, node in enumerate(nodes):
            positions[str(node["id"])] = (index * 200.0, 0.0)
        min_x, max_x = 0.0, max(0.0, (len(nodes) - 1) * 200.0)
        min_y = max_y = 0.0
    box_w, box_h, pad = 164, 46, 46
    svg_w = int(max(360, min(1100, (max_x - min_x) + box_w + pad * 2)))
    svg_h = int(max(180, min(640, (max_y - min_y) + box_h + pad * 2)))
    scale = min(1.0, (svg_w - pad * 2) / max(1.0, (max_x - min_x) + box_w))
    scale_y = min(1.0, (svg_h - pad * 2) / max(1.0, (max_y - min_y) + box_h))
    scale = min(scale, scale_y)

    def point(node_id: str) -> tuple[float, float]:
        x, y = positions.get(str(node_id), (0.0, 0.0))
        return (
            (x - min_x) * scale + pad,
            (y - min_y) * scale + pad,
        )

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {svg_w} {svg_h}" '
        f'width="100%" height="auto" role="img" aria-label="Analysis graph">',
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
        '<path d="M 0 0 L 10 5 L 0 10 z" fill="#94a3b8"/></marker></defs>',
        f'<rect width="{svg_w}" height="{svg_h}" fill="#ffffff"/>',
    ]
    for edge in edges:
        if str(edge["from"]) not in positions or str(edge["to"]) not in positions:
            continue
        x1, y1 = point(edge["from"])
        x2, y2 = point(edge["to"])
        x1 += box_w * scale
        y1 += (box_h * scale) / 2
        y2 += (box_h * scale) / 2
        dx = max(40.0, abs(x2 - x1) * 0.5)
        parts.append(
            f'<path d="M {x1:.1f} {y1:.1f} C {x1 + dx:.1f} {y1:.1f}, '
            f'{x2 - dx:.1f} {y2:.1f}, {x2:.1f} {y2:.1f}" fill="none" '
            f'stroke="#94a3b8" stroke-width="1.6" marker-end="url(#arrow)"/>'
        )
    for node in nodes:
        x, y = point(node["id"])
        label = str(node.get("label") or node.get("id"))
        if len(label) > 24:
            label = label[:23] + "…"
        parts.append(
            f'<g><rect x="{x:.1f}" y="{y:.1f}" width="{box_w * scale:.1f}" '
            f'height="{box_h * scale:.1f}" rx="8" fill="#f8fafc" stroke="#c3cfdd"/>'
            f'<text x="{x + 10:.1f}" y="{y + (box_h * scale) / 2 + 4:.1f}" '
            f'font-family="ui-sans-serif, system-ui, sans-serif" font-size="{max(9, 11 * scale):.1f}" '
            f'fill="#0f172a">{_esc(label)}</text></g>'
        )
    parts.append("</svg>")
    return "\n".join(parts)


def _graph_with_titles(graph: dict[str, Any], nodes: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of the graph whose nodes carry human-readable titles."""
    import copy

    enriched = copy.deepcopy(graph or {})
    for node in enriched.get("nodes") or []:
        record = nodes.get(str(node.get("id"))) or {}
        if record.get("title"):
            node["label"] = record["title"]
    return enriched


def report_html(run_dir: str | Path) -> str:
    run_dir = Path(run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    nodes = manifest.get("nodes") or {}
    order = manifest.get("order") or list(nodes)
    cache = manifest.get("cache") or {}
    summary_rows = [
        ["Run", manifest.get("run_id")],
        ["Status", manifest.get("status")],
        ["Started", manifest.get("started_at")],
        ["Finished", manifest.get("finished_at")],
        ["Wall time", f"{manifest.get('wall_duration_s', 0)} s"],
        ["Total node time", f"{manifest.get('total_duration_s', 0)} s"],
        ["Slowest node", manifest.get("slowest_node", {}).get("id") or "—"],
        ["Cache", f"{cache.get('hits', 0)} hit / {cache.get('misses', 0)} miss"],
        ["Workdir", manifest.get("workdir")],
    ]
    timeline_rows = [
        [node_id, nodes[node_id].get("title"), nodes[node_id].get("status"),
         f"{nodes[node_id].get('duration_s') or 0}",
         "yes" if nodes[node_id].get("cache_hit") else ""]
        for node_id in order
        if node_id in nodes
    ]
    methods = "\n".join(
        f"<li><b>{_esc(nodes[node_id].get('title'))}</b> — "
        f"<code>{_esc(nodes[node_id].get('type'))}</code></li>"
        for node_id in order if node_id in nodes
    )
    sections = "\n".join(
        _node_section(run_dir, nodes[node_id]) for node_id in order if node_id in nodes
    )
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{_esc(manifest.get('name') or manifest.get('run_id'))}</title>
<style>
:root {{ --ink:#0f172a; --muted:#64748b; --line:#dbe3ec; --bg:#ffffff; --soft:#f8fafc; --accent:#2563eb; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--soft); color:var(--ink);
  font:14px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif; }}
main {{ max-width:1080px; margin:0 auto; padding:32px 24px 64px; background:var(--bg); }}
h1 {{ font-size:26px; margin:0 0 4px; }}
h2 {{ font-size:18px; margin:30px 0 10px; border-bottom:1px solid var(--line); padding-bottom:6px; }}
h3 {{ font-size:15px; margin:0; }}
h4 {{ font-size:12px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); margin:14px 0 6px; }}
.muted {{ color:var(--muted); }}
.subtitle {{ color:var(--muted); margin-bottom:20px; }}
table {{ width:100%; border-collapse:collapse; font-size:12px; margin:6px 0; }}
th,td {{ border-bottom:1px solid var(--line); padding:5px 7px; text-align:left; vertical-align:top; }}
th {{ color:var(--muted); font-weight:600; }}
.pill {{ font-size:10px; padding:1px 7px; border-radius:999px; background:#e2e8f0; color:#334155;
  text-transform:uppercase; letter-spacing:.04em; }}
.cache {{ color:#047857; font-weight:600; }}
.node {{ border:1px solid var(--line); border-radius:10px; padding:14px 16px; margin:14px 0; }}
.meta {{ color:var(--muted); font-size:12px; margin-top:4px; }}
.artifact {{ border:1px dashed var(--line); border-radius:8px; padding:10px; margin:8px 0; }}
.artifact-head {{ display:flex; justify-content:space-between; gap:10px; font-size:12px; }}
.artifact img {{ display:block; max-width:100%; margin:10px auto; border:1px solid var(--line); border-radius:6px; }}
code {{ background:#f1f5f9; padding:1px 5px; border-radius:4px; font-size:11px; }}
@media print {{
  body {{ background:#fff; }}
  main {{ max-width:none; padding:0; }}
  .node {{ break-inside:avoid; }}
  .artifact img {{ max-height:520px; width:auto; }}
}}
</style></head><body><main>
<h1>{_esc(manifest.get('name') or 'Omics Canvas run')}</h1>
<div class="subtitle">Run {_esc(manifest.get('run_id'))} · generated {_esc(datetime.now().strftime('%Y-%m-%d %H:%M'))}</div>

<h2>Analysis graph</h2>
{graph_svg(_graph_with_titles(manifest.get('graph') or {}, nodes))}

<h2>Summary</h2>
{_table(summary_rows, ['field', 'value'])}

<h2>Node timeline</h2>
{_table(timeline_rows, ['node', 'title', 'status', 'seconds', 'cached'])}

<h2>Methods</h2>
<p class="muted">The graph below was executed by Omics Canvas. Each node is a separate
R step; parameter values and timings are recorded per node.</p>
<ul>{methods}</ul>

<h2>Results</h2>
{sections}

<h2>Reproducibility</h2>
<p class="muted">Download the run bundle to obtain one R driver per node, the graph,
the manifest, the full artifacts and <code>run_all.sh</code>. Node inputs are
resolved from the absolute paths recorded in each <code>task.json</code>.</p>
</main></body></html>"""


def _driver_script(run_dir: Path, node_id: str, node: dict[str, Any]) -> str:
    graph_node = next(
        (n for n in (json.loads((run_dir / "graph.json").read_text(encoding="utf-8")).get("nodes") or [])
         if n.get("id") == node_id),
        {},
    )
    node_type = node.get("type") or graph_node.get("type", "")
    # The catalog is authoritative for r_file/r_function; fall back to the
    # recorded task.
    task_path = run_dir / node_id / "task.json"
    task = json.loads(task_path.read_text(encoding="utf-8")) if task_path.exists() else {}
    r_file = task.get("r_file", "")
    r_function = task.get("r_function", "run")
    if task.get("language") == "python":
        py_file = task.get("py_file", "")
        try:
            py_rel = str(Path(py_file).resolve().relative_to(PLUGIN_ROOT))
        except (ValueError, OSError):
            py_rel = py_file
        return (
            f"# Reproduce Python node {node_id} from run {run_dir.name}\n"
            f"# Node type: {node_type}\n"
            f"import importlib.util, json, sys\n"
            f"from pathlib import Path\n"
            f"sys.path.insert(0, \"py\")\n"
            f"task = json.loads(Path(\"artifacts/{node_id}/task.json\").read_text())\n"
            f"task[\"outdir\"] = \"artifacts/{node_id}\"\n"
            f"task[\"py_file\"] = \"py/{py_rel}\"\n"
            f"spec = importlib.util.spec_from_file_location(\"node\", task[\"py_file\"])\n"
            f"module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)\n"
            f"result = module.{r_function}(task)\n"
            f"Path(\"artifacts/{node_id}/result.reproduced.json\").write_text(\n"
            f"    json.dumps(result, indent=2, ensure_ascii=False, default=str))\n"
        )
    return (
        f"# Reproduce node {node_id} from run {run_dir.name}\n"
        f"# Node type: {node_type}\n"
        f"# Inputs are read from the recorded task.json (absolute paths).\n"
        f"source(\"r/common.R\")\n"
        f"source(\"r/{r_file}\")\n"
        f"override <- file.path(\"r/overrides\", paste0(gsub(\"[^A-Za-z0-9_]\", \"_\", \"{node_type}\"), \".R\"))\n"
        f"if (file.exists(override)) source(override)\n"
        f"task <- jsonlite::fromJSON(\"artifacts/{node_id}/task.json\")\n"
        f"task$outdir <- \"artifacts/{node_id}\"\n"
        f"result <- {r_function}(task)\n"
        f"jsonlite::write_json(result, \"artifacts/{node_id}/result.reproduced.json\",\n"
        f"  auto_unbox = TRUE, null = \"null\", na = \"null\", digits = NA)\n"
    )


def build_bundle(run_dir: str | Path) -> bytes:
    run_dir = Path(run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    nodes = manifest.get("nodes") or {}
    order = manifest.get("order") or list(nodes)
    tmp = Path(tempfile.mkdtemp(prefix="omics-canvas-bundle-"))
    try:
        (tmp / "artifacts").mkdir()
        (tmp / "code").mkdir()
        shutil.copy2(run_dir / "manifest.json", tmp / "manifest.json")
        if (run_dir / "graph.json").exists():
            shutil.copy2(run_dir / "graph.json", tmp / "graph.json")
        (tmp / "report.html").write_text(report_html(run_dir), encoding="utf-8")
        graph_data = json.loads((run_dir / "graph.json").read_text(encoding="utf-8")) \
            if (run_dir / "graph.json").exists() else {}
        (tmp / "graph.svg").write_text(
            graph_svg(_graph_with_titles(graph_data, nodes)), encoding="utf-8"
        )

        # Source tree needed to rerun individual nodes.
        (tmp / "r").mkdir(exist_ok=True)
        for name in ("common.R", "dispatch.R", "rna_nodes.R", "prot_nodes.R"):
            source = R_DIR / name
            if source.exists():
                shutil.copy2(source, tmp / "r" / name)
        for sub in ("custom", "overrides"):
            source_dir = R_DIR / sub
            if source_dir.exists():
                shutil.copytree(source_dir, tmp / "r" / sub, dirs_exist_ok=True)
        py_source = PLUGIN_ROOT / "py"
        if py_source.exists():
            shutil.copytree(py_source, tmp / "py", dirs_exist_ok=True)

        for node_id in order:
            node = nodes.get(node_id)
            if not node:
                continue
            node_dir = run_dir / node_id
            target = tmp / "artifacts" / node_id
            target.mkdir(parents=True, exist_ok=True)
            for name in ("task.json", "result.json"):
                source = node_dir / name
                if source.exists():
                    shutil.copy2(source, target / name)
            for artifact in (node.get("artifacts") or {}).values():
                source = run_dir / artifact.get("path", "")
                if source.is_file():
                    destination = target / source.name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
            suffix = ".py" if node.get("language") == "python" else ".R"
            (tmp / "code" / f"{node_id}{suffix}").write_text(
                _driver_script(run_dir, node_id, node), encoding="utf-8"
            )

        readme = [
            f"# {manifest.get('name') or 'Omics Canvas run'}",
            "",
            f"- Run: `{manifest.get('run_id')}`",
            f"- Status: `{manifest.get('status')}`",
            f"- Total node time: {manifest.get('total_duration_s', 0)} s",
            f"- Cache: {manifest.get('cache', {}).get('hits', 0)} hit / "
            f"{manifest.get('cache', {}).get('misses', 0)} miss",
            "",
            "## Layout",
            "- `report.html` — publication-friendly report with figures and table previews",
            "- `artifacts/<node>/` — full tables, figures, task/result JSON",
            "- `code/<node>.R` — one reproducible R driver per node",
            "- `graph.json` / `manifest.json` — the exact graph and run record",
            "",
            "## Rerun the whole graph",
            "```bash",
            "python -m omics_canvas run graph.json --no-cache",
            "```",
            "",
            "The absolute data paths recorded in each node's `task.json` must still exist.",
        ]
        (tmp / "README.md").write_text("\n".join(readme) + "\n", encoding="utf-8")
        (tmp / "run_all.sh").write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\ncd \"$(dirname \"$0\")\"\n"
            "python -m omics_canvas run graph.json --no-cache\n",
            encoding="utf-8",
        )

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(tmp.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(tmp).as_posix())
        return buffer.getvalue()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
