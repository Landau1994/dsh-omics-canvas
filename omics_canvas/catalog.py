"""Node catalog loaded from the built-in YAML manifest plus custom nodes."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = Path(__file__).resolve().parent / "specs" / "nodes.yaml"
CUSTOM_SPEC_DIR = Path(__file__).resolve().parent / "specs" / "custom_nodes"
CUSTOM_CODE_DIR = PLUGIN_ROOT / "r" / "custom"
PY_CODE_DIR = PLUGIN_ROOT / "py" / "custom"
OVERRIDE_DIR = PLUGIN_ROOT / "r" / "overrides"
BUILTIN_R_DIR = PLUGIN_ROOT / "r"

CUSTOM_CATEGORY = {"id": "custom", "label": "Custom nodes", "color": "#7c3aed"}

PORT_TYPES = {"matrix", "table", "plot", "any"}
PARAM_TYPES = {"string", "text", "number", "integer", "boolean", "enum", "json", "file"}


def safe_node_id(node_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", str(node_id))


def _validate_python_code(code: str, function_name: str = "run") -> None:
    text = str(code or "")
    if not text.strip():
        raise ValueError("Code must not be empty.")
    if not re.search(rf"(^|\n)\s*def\s+{re.escape(function_name)}\s*\(", text):
        raise ValueError(
            f"Python code must define 'def {function_name}(task):'."
        )
    try:
        compile(text, "<omics-canvas-node>", "exec")
    except SyntaxError as exc:
        raise ValueError(f"Python syntax error: {exc}") from exc


def _validate_r_code(code: str, function_name: str) -> None:
    """Reject code that does not parse or does not define the expected function.

    The check runs through the same Rscript that will execute the node, so a
    failed save leaves the previous implementation in place.
    """
    text = str(code or "")
    if not text.strip():
        raise ValueError("Code must not be empty.")
    pattern = re.compile(
        rf"(^|\n)\s*{re.escape(function_name)}\s*(<-|=)\s*function\b",
        re.MULTILINE,
    )
    if not pattern.search(text):
        raise ValueError(
            f"Code must define '{function_name} <- function(task) {{ ... }}'."
        )
    try:
        from .rbridge import resolve_rscript

        rscript = resolve_rscript()
    except Exception:
        # R is not available in this process; the syntax check still runs when
        # the node is executed.
        return
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".R", delete=False, encoding="utf-8"
    )
    try:
        handle.write(text)
        handle.close()
        proc = subprocess.run(
            [rscript, "--vanilla", "-e", f"parse(file={json.dumps(handle.name)})"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip().splitlines()
            raise ValueError("R parse error: " + (" / ".join(detail[-4:]) or "unknown error"))
    finally:
        handle.close()
        if os.path.exists(handle.name):
            os.unlink(handle.name)


@dataclass
class Port:
    id: str
    label: str
    type: str

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label, "type": self.type}


@dataclass
class Param:
    name: str
    label: str
    type: str = "string"
    default: Any = None
    required: bool = False
    options: list[Any] | None = None
    help: str = ""
    min: Any = None
    max: Any = None
    step: Any = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "label": self.label,
            "type": self.type,
            "default": self.default,
            "required": self.required,
            "help": self.help,
        }
        if self.options is not None:
            data["options"] = self.options
        if self.min is not None:
            data["min"] = self.min
        if self.max is not None:
            data["max"] = self.max
        if self.step is not None:
            data["step"] = self.step
        return data


@dataclass
class NodeSpec:
    id: str
    title: str
    category: str
    r_function: str
    r_file: str
    description: str = ""
    inputs: list[Port] = field(default_factory=list)
    outputs: list[Port] = field(default_factory=list)
    params: list[Param] = field(default_factory=list)
    custom: bool = False
    language: str = "r"
    py_file: str = ""

    def input(self, port_id: str) -> Port | None:
        return next((p for p in self.inputs if p.id == port_id), None)

    def output(self, port_id: str) -> Port | None:
        return next((p for p in self.outputs if p.id == port_id), None)

    def params_by_name(self) -> dict[str, Param]:
        return {p.name: p for p in self.params}

    def defaults(self) -> dict[str, Any]:
        return {p.name: p.default for p in self.params if p.default is not None}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "category": self.category,
            "r_function": self.r_function,
            "r_file": self.r_file,
            "description": self.description,
            "inputs": [p.to_dict() for p in self.inputs],
            "outputs": [p.to_dict() for p in self.outputs],
            "params": [p.to_dict() for p in self.params],
            "custom": self.custom,
            "language": self.language,
            "py_file": self.py_file,
        }


class Catalog:
    def __init__(self, path: str | Path = SPEC_PATH):
        self.path = Path(path)
        with self.path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        self.plugin: dict[str, Any] = raw.get("plugin", {})
        self.categories: list[dict[str, Any]] = list(raw.get("categories", []))
        self.nodes: dict[str, NodeSpec] = {}
        for entry in raw.get("nodes", []):
            spec = self._spec_from_entry(entry)
            if spec.id in self.nodes:
                raise ValueError(f"Duplicate node id in catalog: {spec.id}")
            self.nodes[spec.id] = spec

        custom = self._load_custom_nodes()
        if custom:
            if not any(category.get("id") == "custom" for category in self.categories):
                self.categories.append(dict(CUSTOM_CATEGORY))
            for spec in custom:
                if spec.id in self.nodes:
                    raise ValueError(f"Custom node collides with a built-in id: {spec.id}")
                self.nodes[spec.id] = spec

    @staticmethod
    def _spec_from_entry(entry: dict[str, Any], custom: bool = False) -> NodeSpec:
        return NodeSpec(
            id=str(entry["id"]),
            title=str(entry.get("title", entry["id"])),
            category=str(entry.get("category", "")),
            r_function=str(entry.get("r_function", "run")),
            r_file=str(entry.get("r_file", "" if entry.get("language") == "python" else "common.R")),
            py_file=str(entry.get("py_file", "")),
            language=str(entry.get("language", "r")),
            description=str(entry.get("description", "")),
            inputs=[Port(**p) for p in entry.get("inputs", [])],
            outputs=[Port(**p) for p in entry.get("outputs", [])],
            params=[Param(**p) for p in entry.get("params", [])],
            custom=custom,
        )

    def _load_custom_nodes(self) -> list[NodeSpec]:
        if not CUSTOM_SPEC_DIR.exists():
            return []
        specs: list[NodeSpec] = []
        for path in sorted(CUSTOM_SPEC_DIR.glob("*.json")):
            try:
                entry = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"Invalid custom node file {path.name}: {exc}") from exc
            entry.setdefault("category", "custom")
            entry["custom"] = True
            specs.append(self._spec_from_entry(entry, custom=True))
        return specs

    def get(self, node_type: str) -> NodeSpec:
        try:
            return self.nodes[node_type]
        except KeyError as exc:
            raise KeyError(f"Unknown node type: {node_type}") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin": self.plugin,
            "categories": self.categories,
            "nodes": [spec.to_dict() for spec in self.nodes.values()],
        }


def load_catalog(path: str | Path = SPEC_PATH) -> Catalog:
    return Catalog(path)


# ---------------------------------------------------------------------------
# Custom node and code editing helpers
# ---------------------------------------------------------------------------

def _normalise_ports(raw: Any, kind: str) -> list[dict[str, str]]:
    if raw in (None, ""):
        return []
    if isinstance(raw, str):
        # Accept "expr:matrix, samples:table" from the UI.
        entries = []
        for chunk in raw.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            if ":" in chunk:
                port_id, port_type = chunk.split(":", 1)
            else:
                port_id, port_type = chunk, "matrix"
            entries.append({"id": port_id.strip(), "label": port_id.strip(),
                            "type": port_type.strip() or "matrix"})
        raw = entries
    ports = []
    for port in raw:
        port_id = str(port.get("id", "")).strip()
        if not port_id:
            raise ValueError(f"{kind} port is missing an id")
        port_type = str(port.get("type", "matrix")).strip()
        if port_type not in PORT_TYPES:
            raise ValueError(f"Unsupported {kind} port type: {port_type}")
        ports.append({
            "id": port_id,
            "label": str(port.get("label", port_id)),
            "type": port_type,
        })
    return ports


def _normalise_params(raw: Any) -> list[dict[str, Any]]:
    if raw in (None, ""):
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"parameters must be a JSON array: {exc}") from exc
    params = []
    for param in raw:
        name = str(param.get("name", "")).strip()
        if not name:
            raise ValueError("parameter is missing a name")
        param_type = str(param.get("type", "string"))
        if param_type not in PARAM_TYPES:
            raise ValueError(f"Unsupported parameter type: {param_type}")
        normalised = {
            "name": name,
            "label": str(param.get("label", name)),
            "type": param_type,
            "default": param.get("default"),
            "required": bool(param.get("required", False)),
            "help": str(param.get("help", "")),
        }
        if param.get("options") is not None:
            normalised["options"] = list(param["options"])
        for key in ("min", "max", "step"):
            if param.get(key) is not None:
                normalised[key] = param[key]
        params.append(normalised)
    return params


def upsert_custom_node(node: dict[str, Any], code: str) -> dict[str, Any]:
    node_id = str(node.get("id", "")).strip()
    if not re.fullmatch(r"custom\.[A-Za-z0-9_.-]+", node_id):
        raise ValueError("Custom node ids must look like 'custom.<name>'.")
    language = str(node.get("language", "r")).strip().lower()
    if language not in {"r", "python"}:
        raise ValueError("Custom node language must be 'r' or 'python'.")
    title = str(node.get("title", node_id)).strip() or node_id
    description = str(node.get("description", "")).strip()
    inputs = _normalise_ports(node.get("inputs"), "input")
    outputs = _normalise_ports(node.get("outputs"), "output")
    params = _normalise_params(node.get("params"))

    safe = safe_node_id(node_id)
    entry = {
        "id": node_id,
        "title": title,
        "category": "custom",
        "description": description,
        "language": language,
        "r_function": "run",
        "inputs": inputs,
        "outputs": outputs,
        "params": params,
    }

    CUSTOM_SPEC_DIR.mkdir(parents=True, exist_ok=True)
    if language == "python":
        _validate_python_code(str(code), "run")
        entry["py_file"] = f"custom/{safe}.py"
        entry["r_file"] = ""
        PY_CODE_DIR.mkdir(parents=True, exist_ok=True)
        (PY_CODE_DIR / f"{safe}.py").write_text(
            str(code).rstrip() + "\n", encoding="utf-8"
        )
        # Remove a previous R implementation if the language changed.
        stale = CUSTOM_CODE_DIR / f"{safe}.R"
        if stale.exists():
            stale.unlink()
    else:
        _validate_r_code(str(code), "run")
        entry["r_file"] = f"custom/{safe}.R"
        entry["py_file"] = ""
        CUSTOM_CODE_DIR.mkdir(parents=True, exist_ok=True)
        (CUSTOM_CODE_DIR / f"{safe}.R").write_text(
            str(code).rstrip() + "\n", encoding="utf-8"
        )
        stale = PY_CODE_DIR / f"{safe}.py"
        if stale.exists():
            stale.unlink()

    (CUSTOM_SPEC_DIR / f"{safe}.json").write_text(
        json.dumps(entry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return entry


def delete_custom_node(node_id: str) -> None:
    if not str(node_id).startswith("custom."):
        raise ValueError("Only custom nodes can be deleted.")
    safe = safe_node_id(node_id)
    spec = CUSTOM_SPEC_DIR / f"{safe}.json"
    r_code = CUSTOM_CODE_DIR / f"{safe}.R"
    py_code = PY_CODE_DIR / f"{safe}.py"
    override = OVERRIDE_DIR / f"{safe}.R"
    for path in (spec, r_code, py_code, override):
        if path.exists():
            path.unlink()


def _extract_r_function(source: str, function_name: str) -> str | None:
    """Return one top-level R function definition (comments/strings aware)."""
    pattern = re.compile(
        rf"(?m)^\s*{re.escape(function_name)}\s*<-\s*function\s*\("
    )
    match = pattern.search(source)
    if not match:
        return None
    brace = source.find("{", match.end())
    if brace < 0:
        return None
    depth = 0
    index = brace
    quote = None
    escaped = False
    while index < len(source):
        char = source[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        else:
            if char in ("'", '"'):
                quote = char
            elif char == "#":
                newline = source.find("\n", index)
                index = len(source) if newline < 0 else newline
                continue
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return source[match.start():index + 1].strip()
        index += 1
    return None


def _python_code_template() -> str:
    return (
        "def run(task):\n"
        "    import pandas as pd\n"
        "    from common import write_table\n"
        "\n"
        "    outdir = task[\"outdir\"]\n"
        "    # task[\"params\"] : dict of parameters\n"
        "    # task[\"inputs\"] : dict of absolute artifact paths\n"
        "    frame = pd.DataFrame({\"value\": [1, 2, 3]})\n"
        "    write_table(frame, outdir + \"/python_output.tsv\")\n"
        "    return {\n"
        "        \"ok\": True,\n"
        "        \"artifacts\": {\n"
        "            \"out\": {\"file\": \"python_output.tsv\", \"type\": \"table\", \"label\": \"Python output\"}\n"
        "        },\n"
        "        \"metrics\": {\"n\": len(frame)},\n"
        "        \"messages\": [],\n"
        "    }\n"
    )


def _builtin_code_template(node_id: str, r_function: str) -> str:
    return (
        f"# Override for node: {node_id}\n"
        f"# The built-in implementation is replaced by this function.\n"
        f"# Available helpers: source(\"r/common.R\") is already loaded.\n"
        f"{r_function} <- function(task) {{\n"
        f"  outdir <- task$outdir\n"
        f"  # task$params : named list of parameters\n"
        f"  # task$inputs : named list of absolute artifact paths\n"
        f"  list(\n"
        f"    ok = TRUE,\n"
        f"    artifacts = list(),\n"
        f"    metrics = list(),\n"
        f"    messages = character()\n"
        f"  )\n"
        f"}}\n"
    )


def read_node_code(catalog: Catalog, node_id: str) -> dict[str, Any]:
    spec = catalog.get(node_id)
    if spec.custom:
        language = spec.language or "r"
        if language == "python":
            path = PY_CODE_DIR / f"{safe_node_id(node_id)}.py"
            code = path.read_text(encoding="utf-8") if path.exists() else _python_code_template()
        else:
            path = CUSTOM_CODE_DIR / f"{safe_node_id(node_id)}.R"
            code = path.read_text(encoding="utf-8") if path.exists() else ""
        return {
            "node_id": node_id,
            "kind": "custom",
            "language": language,
            "r_function": spec.r_function,
            "code": code,
            "builtin": False,
            "has_override": False,
        }

    override = OVERRIDE_DIR / f"{safe_node_id(node_id)}.R"
    if override.exists():
        return {
            "node_id": node_id,
            "kind": "override",
            "language": "r",
            "r_function": spec.r_function,
            "code": override.read_text(encoding="utf-8"),
            "builtin": True,
            "has_override": True,
        }

    builtin_path = BUILTIN_R_DIR / spec.r_file
    builtin_code = builtin_path.read_text(encoding="utf-8") if builtin_path.exists() else ""
    extracted = _extract_r_function(builtin_code, spec.r_function)
    return {
        "node_id": node_id,
        "kind": "builtin" if extracted else "template",
        "language": "r",
        "r_function": spec.r_function,
        "code": extracted or _builtin_code_template(node_id, spec.r_function),
        "builtin": True,
        "has_override": False,
        "builtin_source": builtin_code,
    }


def write_node_code(catalog: Catalog, node_id: str, code: str) -> dict[str, Any]:
    spec = catalog.get(node_id)
    if spec.custom and spec.language == "python":
        _validate_python_code(str(code), spec.r_function)
        path = PY_CODE_DIR / f"{safe_node_id(node_id)}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(code).rstrip() + "\n", encoding="utf-8")
        return read_node_code(catalog, node_id)

    _validate_r_code(str(code), spec.r_function)
    if spec.custom:
        path = CUSTOM_CODE_DIR / f"{safe_node_id(node_id)}.R"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(code).rstrip() + "\n", encoding="utf-8")
        return read_node_code(catalog, node_id)

    OVERRIDE_DIR.mkdir(parents=True, exist_ok=True)
    path = OVERRIDE_DIR / f"{safe_node_id(node_id)}.R"
    path.write_text(str(code).rstrip() + "\n", encoding="utf-8")
    return read_node_code(catalog, node_id)


def delete_node_code(catalog: Catalog, node_id: str) -> dict[str, Any]:
    spec = catalog.get(node_id)
    if spec.custom:
        raise ValueError("Custom node code is deleted with the node itself.")
    path = OVERRIDE_DIR / f"{safe_node_id(node_id)}.R"
    if path.exists():
        path.unlink()
    return read_node_code(catalog, node_id)
