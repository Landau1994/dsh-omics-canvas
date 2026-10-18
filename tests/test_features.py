"""Feature tests: custom nodes, code overrides, cache, report and bundle."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from omics_canvas import cache as result_cache
from omics_canvas.catalog import (
    delete_custom_node,
    delete_node_code,
    load_catalog,
    read_node_code,
    upsert_custom_node,
    write_node_code,
)
from omics_canvas.engine import Graph, Runner
from omics_canvas.report import build_bundle, report_html

ROOT = Path(__file__).resolve().parents[1]
CUSTOM_ID = "custom.pytest_demo"

CUSTOM_CODE = """run <- function(task) {
  outdir <- task$outdir
  write_tsv_file(data.frame(value = c(1, 2, 3)), file.path(outdir, "out.tsv"))
  list(
    ok = TRUE,
    artifacts = list(out = list(file = "out.tsv", type = "table", label = "Out")),
    metrics = list(n = 3),
    messages = character()
  )
}
"""


@pytest.fixture(autouse=True)
def cleanup_custom_node():
    delete_custom_node(CUSTOM_ID)
    yield
    delete_custom_node(CUSTOM_ID)


def create_custom_node(extra_inputs=None):
    return upsert_custom_node(
        {
            "id": CUSTOM_ID,
            "title": "Pytest custom node",
            "description": "Writes a small table.",
            "inputs": extra_inputs or [],
            "outputs": [{"id": "out", "label": "Out", "type": "table"}],
            "params": [],
        },
        CUSTOM_CODE,
    )


def test_custom_node_roundtrip_and_code_editing():
    create_custom_node()
    catalog = load_catalog()
    assert CUSTOM_ID in catalog.nodes
    assert catalog.nodes[CUSTOM_ID].custom

    code = read_node_code(catalog, CUSTOM_ID)
    assert code["kind"] == "custom"
    assert "run <- function" in code["code"]

    edited = write_node_code(
        catalog,
        CUSTOM_ID,
        CUSTOM_CODE.replace('"Out"', '"Edited out"'),
    )
    assert edited["kind"] == "custom"
    assert "Edited out" in edited["code"]

    catalog = load_catalog()
    delete_custom_node(CUSTOM_ID)
    assert CUSTOM_ID not in load_catalog().nodes


def test_invalid_custom_code_is_rejected():
    with pytest.raises(ValueError):
        upsert_custom_node(
            {
                "id": "custom.bad",
                "title": "Bad",
                "inputs": [],
                "outputs": [],
                "params": [],
            },
            "run <- function(task) {",
        )
    assert "custom.bad" not in load_catalog().nodes


def test_builtin_template_and_override():
    catalog = load_catalog()
    template = read_node_code(catalog, "rna.filter")
    assert template["kind"] == "builtin"
    assert "rna_filter <- function(task)" in template["code"]
    assert template["has_override"] is False

    override_code = (
        "rna_filter <- function(task) {\n"
        "  list(ok = TRUE, artifacts = list(), metrics = list(), messages = character())\n"
        "}\n"
    )
    written = write_node_code(catalog, "rna.filter", override_code)
    assert written["kind"] == "override"
    assert written["has_override"] is True

    reset = delete_node_code(catalog, "rna.filter")
    assert reset["kind"] == "builtin"
    assert reset["has_override"] is False


def test_any_port_compatibility():
    create_custom_node([{"id": "x", "label": "X", "type": "any"}])
    catalog = load_catalog()
    graph = Graph.from_dict(
        {
            "name": "any-port",
            "nodes": [
                {
                    "id": "load",
                    "type": "rna.load_matrix",
                    "params": {"expression": "x.tsv"},
                },
                {"id": "custom", "type": CUSTOM_ID, "params": {}},
            ],
            "edges": [
                {"from": "load", "from_port": "expr", "to": "custom", "to_port": "x"}
            ],
        }
    )
    errors = graph.validate(catalog)
    assert not any("type mismatch" in error for error in errors), errors


def test_cache_hit_on_second_run(tmp_path):
    create_custom_node()
    cache_dir = tmp_path / "cache"
    runner = Runner(
        load_catalog(),
        runs_dir=tmp_path / "runs",
        workdir=tmp_path,
        env="scptools",
        cache_dir=cache_dir,
    )
    graph = Graph.from_dict(
        {
            "name": "cache",
            "nodes": [{"id": "custom", "type": CUSTOM_ID, "params": {}}],
            "edges": [],
        }
    )
    first = runner.run(graph, tmp_path / "run1")
    second = runner.run(graph, tmp_path / "run2")
    assert first["nodes"]["custom"]["cache_hit"] is False
    assert second["nodes"]["custom"]["cache_hit"] is True
    assert second["cache"]["hits"] == 1
    assert (tmp_path / "run2" / "custom" / "out.tsv").exists()
    assert result_cache.stats(cache_dir)["entries"] >= 1


def test_cache_key_sensitivity(tmp_path):
    code = tmp_path / "node.R"
    code.write_text(CUSTOM_CODE, encoding="utf-8")
    base = result_cache.compute_key("custom.x", {"a": 1}, {}, [code], "scptools")
    assert base == result_cache.compute_key("custom.x", {"a": 1}, {}, [code], "scptools")
    assert base != result_cache.compute_key("custom.x", {"a": 2}, {}, [code], "scptools")
    code.write_text(CUSTOM_CODE + "\n# changed\n", encoding="utf-8")
    assert base != result_cache.compute_key("custom.x", {"a": 1}, {}, [code], "scptools")


def _synthetic_run(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    (run / "node").mkdir(parents=True)
    png = base64_png()
    (run / "node" / "out.tsv").write_text("a\tb\n1\t2\n", encoding="utf-8")
    (run / "node" / "plot.png").write_bytes(png)
    manifest = {
        "run_id": "run",
        "run_dir": str(run),
        "name": "Synthetic run",
        "status": "success",
        "started_at": "2026-01-01T00:00:00+08:00",
        "finished_at": "2026-01-01T00:00:10+08:00",
        "total_duration_s": 1.2,
        "wall_duration_s": 2.4,
        "slowest_node": {"id": "node", "duration_s": 1.2},
        "cache": {"enabled": True, "hits": 1, "misses": 0},
        "order": ["node"],
        "nodes": {
            "node": {
                "id": "node",
                "type": "custom.demo",
                "title": "Demo node",
                "status": "success",
                "duration_s": 1.2,
                "cache_hit": True,
                "params": {"x": 1},
                "metrics": {"n": 2},
                "messages": ["ok"],
                "artifacts": {
                    "out": {"port": "out", "type": "table", "label": "Out",
                            "file": "out.tsv", "path": "node/out.tsv",
                            "size_bytes": 8},
                    "plot": {"port": "plot", "type": "plot", "label": "Plot",
                             "file": "plot.png", "path": "node/plot.png",
                             "size_bytes": len(png)},
                },
            }
        },
        "graph": {
            "name": "Synthetic run",
            "nodes": [{"id": "node", "type": "custom.demo", "x": 40, "y": 40}],
            "edges": [],
        },
    }
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run / "graph.json").write_text(json.dumps(manifest["graph"]), encoding="utf-8")
    (run / "node" / "task.json").write_text(json.dumps({"node": "node"}), encoding="utf-8")
    return run


def base64_png() -> bytes:
    # 1x1 transparent PNG.
    import base64

    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
        "/x8AAusB9Wl2n1cAAAAASUVORK5CYII="
    )


def test_report_and_bundle(tmp_path):
    run = _synthetic_run(tmp_path)
    html = report_html(run)
    assert "Analysis graph" in html
    assert "<svg" in html
    assert "data:image/png;base64" in html
    assert "cached" in html
    assert "Wall time" in html
    assert "Demo node" in html

    bundle = build_bundle(run)
    archive = zipfile.ZipFile(io.BytesIO(bundle))
    names = set(archive.namelist())
    assert "report.html" in names
    assert "graph.svg" in names
    assert "code/node.R" in names
    assert "run_all.sh" in names
    assert "README.md" in names
    assert "artifacts/node/out.tsv" in names


def test_bundle_contains_python_driver(tmp_path):
    run = _synthetic_run(tmp_path)
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    node = manifest["nodes"]["node"]
    node["language"] = "python"
    node["env"] = "scptools"
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    task = {
        "node": "node",
        "language": "python",
        "py_file": str(ROOT / "py" / "custom" / "demo.py"),
        "r_function": "run",
        "outdir": str(run / "node"),
    }
    (run / "node" / "task.json").write_text(json.dumps(task), encoding="utf-8")
    bundle = build_bundle(run)
    archive = zipfile.ZipFile(io.BytesIO(bundle))
    names = set(archive.namelist())
    assert "code/node.py" in names
    assert "py/dispatch.py" in names
    assert "def run" not in archive.read("code/node.py").decode("utf-8")
    assert "importlib" in archive.read("code/node.py").decode("utf-8")


def test_heatmap_has_customization_params():
    catalog = load_catalog()
    for node_id in ("rna.heatmap", "prot.heatmap"):
        names = {param.name for param in catalog.get(node_id).params}
        assert {"feature_list", "cluster_rows", "cluster_columns", "show_row_names",
                "z_cap", "color_low", "color_high", "width", "height"} <= names


def test_canvas_document_roundtrip(tmp_path, monkeypatch):
    from omics_canvas import server

    monkeypatch.setattr(server, "CANVAS_DIR", tmp_path / "canvases")
    graph = {
        "name": "sync test",
        "nodes": [
            {"id": "n1", "type": "rna.load_matrix", "params": {"matrix": "x.tsv"}, "x": 0, "y": 0},
        ],
        "edges": [],
    }
    saved = server.save_canvas("demo_canvas", graph)
    assert saved["revision"] == 1
    loaded = server.load_canvas("demo_canvas")
    assert loaded["graph"]["nodes"][0]["id"] == "n1"

    patched = server.apply_canvas_ops(
        loaded["graph"],
        [{"op": "set_node_params", "node_id": "n1", "params": {"matrix": "y.tsv"}}],
    )
    assert patched["nodes"][0]["params"]["matrix"] == "y.tsv"
    updated = server.save_canvas("demo_canvas", patched)
    assert updated["revision"] == 2
