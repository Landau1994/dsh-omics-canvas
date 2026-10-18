"""Python custom nodes, per-node conda environments and code editing."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from omics_canvas.catalog import (
    delete_custom_node,
    load_catalog,
    read_node_code,
    upsert_custom_node,
    write_node_code,
)
from omics_canvas.engine import Graph, Runner
from omics_canvas.rbridge import list_environments, resolve_python, resolve_rscript

ROOT = Path(__file__).resolve().parents[1]
NODE_ID = "custom.pytest_python"
CODE = '''def run(task):
    import os
    outdir = task["outdir"]
    path = os.path.join(outdir, "python_out.tsv")
    with open(path, "w") as fh:
        fh.write("value\\n1\\n2\\n")
    return {
        "ok": True,
        "artifacts": {"out": {"file": "python_out.tsv", "type": "table", "label": "Python out"}},
        "metrics": {"n": 2},
        "messages": ["python node ran"],
    }
'''


@pytest.fixture(autouse=True)
def cleanup():
    delete_custom_node(NODE_ID)
    yield
    delete_custom_node(NODE_ID)


def make_node():
    return {
        "id": NODE_ID,
        "language": "python",
        "title": "Pytest Python node",
        "description": "Writes a table.",
        "inputs": [],
        "outputs": [{"id": "out", "label": "Out", "type": "table"}],
        "params": [],
    }


def test_conda_scptools_interpreter():
    python = resolve_python("scptools")
    rscript = resolve_rscript("scptools")
    assert "scptools" in python and python.endswith("python")
    assert "scptools" in rscript and rscript.endswith("Rscript")
    assert "scptools" in list_environments()


def test_python_node_roundtrip_and_run(tmp_path):
    entry = upsert_custom_node(make_node(), CODE)
    assert entry["language"] == "python"
    assert entry["py_file"].startswith("custom/")

    catalog = load_catalog()
    assert catalog.nodes[NODE_ID].language == "python"
    code = read_node_code(catalog, NODE_ID)
    assert code["kind"] == "custom"
    assert code["language"] == "python"
    assert "def run(task)" in code["code"]

    edited = write_node_code(catalog, NODE_ID, CODE.replace('"Python out"', '"Edited"'))
    assert edited["kind"] == "custom"
    assert "Edited" in edited["code"]

    graph = Graph.from_dict(
        {
            "name": "python cache",
            "nodes": [{"id": "demo", "type": NODE_ID, "params": {}, "env": "scptools"}],
            "edges": [],
        }
    )
    runner = Runner(
        load_catalog(),
        runs_dir=tmp_path / "runs",
        workdir=tmp_path,
        env="scptools",
        cache_dir=tmp_path / "cache",
    )
    first = runner.run(graph, tmp_path / "run1")
    second = runner.run(graph, tmp_path / "run2")
    assert first["nodes"]["demo"]["status"] == "success"
    assert first["nodes"]["demo"]["env"] == "scptools"
    assert (tmp_path / "run1" / "demo" / "python_out.tsv").exists()
    assert second["nodes"]["demo"]["cache_hit"] is True


def test_invalid_python_code_is_rejected():
    with pytest.raises(ValueError):
        upsert_custom_node(make_node(), "def run(task)\n    return {}")
    assert NODE_ID not in load_catalog().nodes


def test_graph_env_roundtrip():
    graph = Graph.from_dict(
        {
            "name": "env",
            "nodes": [
                {
                    "id": "load",
                    "type": "rna.load_matrix",
                    "params": {"expression": "x.tsv"},
                    "env": "base",
                }
            ],
            "edges": [],
        }
    )
    assert graph.node("load").env == "base"
    assert graph.to_dict()["nodes"][0]["env"] == "base"


def test_per_node_conda_env(tmp_path):
    upsert_custom_node(make_node(), CODE)
    graph = Graph.from_dict(
        {
            "name": "env override",
            "nodes": [{"id": "demo", "type": NODE_ID, "params": {}, "env": "anaconda3"}],
            "edges": [],
        }
    )
    runner = Runner(
        load_catalog(),
        runs_dir=tmp_path / "runs",
        workdir=tmp_path,
        env="scptools",
        cache_dir=tmp_path / "cache",
    )
    manifest = runner.run(graph, tmp_path / "run")
    assert manifest["nodes"]["demo"]["status"] == "success", manifest["nodes"]["demo"].get("error")
    assert manifest["nodes"]["demo"]["env"] == "anaconda3"
