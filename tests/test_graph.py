"""Structural tests for the Omics Canvas catalog and graph engine."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from omics_canvas.catalog import load_catalog
from omics_canvas.engine import Graph, GraphError, resolve_params

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "omics_canvas" / "specs" / "examples"


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


def load_example(name: str) -> Graph:
    return Graph.from_dict(json.loads((EXAMPLES / name).read_text(encoding="utf-8")))


def test_catalog_has_both_domains(catalog):
    assert len(catalog.nodes) >= 18
    categories = {entry["id"] for entry in catalog.categories}
    assert {"rna", "proteomics"}.issubset(categories)


def test_every_node_has_an_r_implementation(catalog):
    for spec in catalog.nodes.values():
        r_file = ROOT / "r" / spec.r_file
        assert r_file.is_file(), f"missing {r_file}"
        assert spec.r_function in r_file.read_text(encoding="utf-8"), (
            f"{spec.r_function} is not defined in {r_file}"
        )


@pytest.mark.parametrize(
    "example",
    ["rna_seq_gse116271.json", "bulk_proteomics_pxd046756.json"],
)
def test_examples_validate(catalog, example):
    graph = load_example(example)
    assert graph.validate(catalog) == []


def test_cycle_is_rejected(catalog):
    graph = Graph.from_dict(
        {
            "name": "cycle",
            "nodes": [
                {"id": "a", "type": "rna.filter"},
                {"id": "b", "type": "rna.filter"},
            ],
            "edges": [
                {"from": "a", "from_port": "expr", "to": "b", "to_port": "expr"},
                {"from": "b", "from_port": "expr", "to": "a", "to_port": "expr"},
                {"from": "a", "from_port": "samples", "to": "b", "to_port": "samples"},
                {"from": "b", "from_port": "samples", "to": "a", "to_port": "samples"},
            ],
        }
    )
    errors = graph.validate(catalog)
    assert any("cycle" in error.lower() for error in errors)


def test_unknown_port_is_rejected(catalog):
    graph = Graph.from_dict(
        {
            "name": "bad port",
            "nodes": [
                {
                    "id": "load",
                    "type": "rna.load_matrix",
                    "params": {"expression": "x.tsv"},
                },
                {"id": "filter", "type": "rna.filter"},
            ],
            "edges": [
                {"from": "load", "from_port": "nope", "to": "filter", "to_port": "expr"},
                {"from": "load", "from_port": "samples", "to": "filter", "to_port": "samples"},
            ],
        }
    )
    errors = graph.validate(catalog)
    assert any("unknown output port" in error for error in errors)


def test_missing_required_parameter_is_rejected(catalog):
    graph = Graph.from_dict(
        {"name": "no params", "nodes": [{"id": "load", "type": "rna.load_matrix"}], "edges": []}
    )
    errors = graph.validate(catalog)
    assert any("required parameter 'expression'" in error for error in errors)


def test_type_mismatch_is_rejected(catalog):
    graph = Graph.from_dict(
        {
            "name": "mismatch",
            "nodes": [
                {
                    "id": "load",
                    "type": "rna.load_matrix",
                    "params": {"expression": "x.tsv"},
                },
                {"id": "volcano", "type": "rna.volcano"},
            ],
            "edges": [
                {"from": "load", "from_port": "expr", "to": "volcano", "to_port": "results"}
            ],
        }
    )
    errors = graph.validate(catalog)
    assert any("type mismatch" in error for error in errors)


def test_execution_order_respects_dependencies(catalog):
    graph = load_example("rna_seq_gse116271.json")
    order = graph.execution_order(catalog)
    assert order.index("load") < order.index("filter")
    assert order.index("filter") < order.index("de")
    assert order.index("de") < order.index("volcano")


def test_target_restricts_to_ancestors(catalog):
    graph = load_example("rna_seq_gse116271.json")
    order = graph.execution_order(catalog, ["volcano"])
    assert "volcano" in order
    assert "load" in order
    assert "filter" in order
    assert "pca" not in order


def test_resolve_params_coerces_and_resolves_files(catalog, tmp_path):
    spec = catalog.get("rna.load_matrix")
    params = resolve_params(
        spec,
        {
            "expression": "relative/matrix.tsv",
            "matrix_type": "counts",
            "collapse_symbols": "true",
        },
        tmp_path,
    )
    assert Path(params["expression"]).is_absolute()
    assert params["expression"].endswith("relative/matrix.tsv")
    assert params["collapse_symbols"] is True
    assert params["matrix_type"] == "counts"
