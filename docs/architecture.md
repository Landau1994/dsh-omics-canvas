# Architecture

## Overview

```text
┌──────────────────────────────────────────────────────────────┐
│ Browser canvas (web/)                                        │
│  palette · nodes · edges · inspector · run status            │
└──────────────────────────────┬───────────────────────────────┘
                               │ JSON over HTTP
┌──────────────────────────────▼───────────────────────────────┐
│ Python engine (omics_canvas/)                                │
│  catalog.py  · engine.py  · server.py  · cli.py  · rbridge.py │
│  validate graph → topo sort → execute nodes → manifest.json   │
└──────────────────────────────┬───────────────────────────────┘
                               │ Rscript task.json
┌──────────────────────────────▼───────────────────────────────┐
│ R nodes (r/) inside conda env scptools                        │
│  dispatch.R → common.R + rna_nodes.R / prot_nodes.R           │
│  DESeq2 · limma · clusterProfiler · ComplexHeatmap · ggplot2  │
└──────────────────────────────┬───────────────────────────────┘
                               │ files
                        runs/<run_id>/
```

The plugin deliberately keeps the analysis in R and the orchestration in
Python. The canvas only speaks a small graph JSON dialect, so another frontend
can replace `web/` without touching the engine or the nodes.

## Layers

### 1. Catalog (`omics_canvas/specs/nodes.yaml`)

The catalog is the plugin manifest. It declares:

- plugin metadata (`id`, `name`, `version`, `environment`),
- categories with UI colours,
- every node: `id`, `title`, `category`, `description`, `r_function`,
  `r_file`, typed input ports, typed output ports, and a parameter schema.

The built-in catalog is extended at load time by `omics_canvas/specs/custom_nodes/*.json`.
A custom node declares `language: "r" | "python"`; R code lives in
`r/custom/<id>.R`, Python code in `py/custom/<id>.py`. Built-in R
implementations can be replaced per node by `r/overrides/<node_type>.R`;
`dispatch.R` sources the override after the built-in file. Port types are
`matrix`, `table`, `plot` or `any`; `any` connects to every type.

Each graph node may carry `env` (a conda environment). The runner uses it for
both R and Python and includes it in the cache key; the default is the
server/plugin `env` (normally `scptools`).

Parameters are rendered directly from the YAML by the browser, so the editor
has no hard-coded node knowledge.

### 2. Graph model (`omics_canvas/engine.py`)

```python
Graph(name, nodes=[Node(id, type, params, x, y)], edges=[Edge(from, from_port, to, to_port)])
```

Validation checks:

- unique node ids and known node types,
- edge endpoints and port names exist,
- output/input port types match (`matrix`, `table`, `plot`),
- at most one edge enters an input port,
- required parameters are present,
- the graph is acyclic (Kahn topological sort).

`execution_order(targets)` can restrict a run to the ancestors of one or more
target nodes, which is useful for iterating on a single downstream node.

### 3. Execution (`Runner`)

For each node in topological order:

1. Mark the node `running` in `manifest.json`.
2. Collect input artifact paths from the artifacts of upstream nodes.
3. Merge parameter defaults and user values; relative `file` parameters are
   resolved against the run's `workdir`.
4. Write `<node>/task.json`.
5. Run `Rscript --vanilla r/dispatch.R <task.json>` in the `scptools`
   environment, capturing stdout/stderr into `logs/<node>.log`.
6. Compute a content-addressed cache key (node type, resolved parameters,
   input file hashes, `common.R`/`dispatch.R`/node source/override hashes and
   the R environment). A hit copies cached artifacts into the node directory
   and skips the R process; a miss runs R and then stores the artifacts.
7. Read `<node>/result.json`, register artifacts in the manifest, mark the node
   `success` or `failed`, and record duration/cache fields.

If a node fails, downstream nodes are marked `skipped` unless
`--keep-going` is used. The manifest is written atomically after every state
change, so the browser can poll it while a run is in progress.

`--resume` reloads an existing manifest and keeps successful nodes whose
artifacts still exist; only failed/pending nodes are re-executed. This is the
intended recovery path for long enrichment steps or interrupted sessions.

### 4. R dispatcher (`r/dispatch.R`)

`dispatch.R` (R nodes) or `py/dispatch.py` (Python nodes):

- parses the task JSON,
- sources `common.R`,
- sources the node's `r_file`,
- calls the named function,
- converts messages/warnings into a `messages` array,
- writes `result.json` and exits non-zero on failure.

R nodes expose `function(task)`; Python nodes expose `def run(task)` receiving
the same values as a dict. Every node returns:

```r
node_function <- function(task) {
  # task$params  : named list of validated parameters
  # task$inputs  : named list of absolute artifact paths
  # task$outdir  : directory where artifacts must be written
  list(
    ok = TRUE,
    artifacts = list(
      port_name = list(file = "file.tsv", type = "table", label = "Readable label")
    ),
    metrics = list(n = 10),
    messages = c("optional note")
  )
}
```

Artifacts are files inside the node directory. Their `port_name` must match an
output port declared in the catalog, because edges reference that port.

`common.R` provides the shared analysis primitives:

| Helper | Purpose |
|---|---|
| `p_str/p_num/p_int/p_bool` | Typed parameter access |
| `input_path` | Resolve and check an input artifact |
| `read_tsv_file` / `write_tsv_file` | Stable TSV IO |
| `df_to_matrix` / `matrix_with_anno` | Matrix ↔ table conversion that preserves ID/annotation columns |
| `align_samples` | Reorder matrix columns to the sample sheet |
| `pca_impl` | PCA, variance table, ggplot |
| `volcano_impl` | Volcano plot + up/down summary |
| `heatmap_impl` | Z-scored ComplexHeatmap with group annotation |
| `ora_impl` / `gsea_impl` | Offline GO enrichment via `clusterProfiler` |
| `save_plot` / `save_heatmap` | PNG + PDF artifact pairs |

### 5. HTTP API (`omics_canvas/server.py`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Canvas editor (`web/index.html`) |
| GET | `/api/catalog` | Catalog (built-in + custom) + example list |
| GET/POST | `/api/custom-nodes` | List / create or update custom nodes |
| DELETE | `/api/custom-nodes/<id>` | Delete a custom node |
| GET/PUT/DELETE | `/api/nodes/<type>/code` | Read, save or reset R/Python node code |
| GET | `/api/environments` | Conda environments for the per-node selector |
| GET/PUT | `/api/canvases/<id>` | Read / save the open canvas document (revision-checked) |
| PATCH | `/api/canvases/<id>` | Apply node-param / edge patches from the agent |
| GET/DELETE | `/api/cache` | Cache stats / clear |
| POST | `/api/validate` | Validate a graph without running it |
| POST | `/api/run` | Start a run in a background thread; returns `run_id` |
| GET | `/api/runs` | List past runs |
| GET | `/api/runs/<run_id>` | Current manifest (poll target) |
| GET | `/api/runs/<run_id>/files/<path>` | Serve an artifact or node log |
| GET | `/api/runs/<run_id>/report` | Self-contained HTML report |
| GET | `/api/runs/<run_id>/export` | ZIP bundle (report, graph SVG, code, artifacts) |
| GET | `/api/examples/<file>` | Serve an example graph |

The server uses the Python standard library (`ThreadingHTTPServer`). Path
resolution rejects traversal outside the run directory or `web/` directory.
It binds to `127.0.0.1` by default and has no authentication, so it is a local
development/analysis surface rather than a public service.

### 6. Browser canvas (`web/`)

`index.html`, `style.css` and `app.js` implement the editor without external
dependencies:

- nodes are absolutely positioned DOM elements inside a transformed `#world`,
- edges are SVG bezier paths with the same coordinate space,
- port positions are derived from the node position and the port index
  (`node.y + header + padding + index * row + row/2`), so the DOM layout and
  edge geometry stay in sync,
- dragging an output port to an input port creates an edge after type checking,
- the inspector is generated from the catalog parameter schema,
- run status is polled from the manifest and mapped onto node CSS classes,
- artifacts (including PNG figures) are shown inline in the inspector,
- the canvas document is mirrored to `/api/canvases/<id>` with optimistic
  revision checks, and polled every 3 s so an agent patch appears in place,
- the agent-edit prompt carries the canvas id and the selected node, so the
  model can patch parameters or write a code override.

Graphs are exported as the same JSON the engine consumes, and the latest graph
is cached in `localStorage` as a fallback. Built-in code shown in the inspector
is extracted from the shipped R function; saving writes an override under
`r/overrides/` and leaves the original file untouched.

## Manifest schema

```json
{
  "run_id": "20261018_231806_rna-seq-...",
  "name": "RNA-seq GSE116271 (foam vs non-foam)",
  "status": "success",
  "started_at": "...",
  "finished_at": "...",
  "order": ["load", "filter", "de", "..."],
  "total_duration_s": 176.2,
  "wall_duration_s": 178.4,
  "slowest_node": { "id": "go_gsea", "duration_s": 71.7 },
  "cache": { "enabled": true, "hits": 9, "misses": 0 },
  "graph": { "nodes": [], "edges": [] },
  "nodes": {
    "de": {
      "status": "success",
      "duration_s": 13.53,
      "language": "r",
      "env": "scptools",
      "cache_hit": false,
      "cache_key": "b9d561f8...",
      "params": { "numerator": "non_foam", "denominator": "foam" },
      "artifacts": {
        "results": {
          "port": "results",
          "type": "table",
          "label": "DE results",
          "path": "de/de_results.tsv",
          "url": "/api/runs/<run_id>/files/de/de_results.tsv",
          "size_bytes": 2088263
        }
      },
      "metrics": { "n_tested": 11329, "n_up": 524, "n_down": 333 },
      "messages": ["524 up and 333 down ..."],
      "log": "logs/de.log"
    }
  },
  "artifacts": { "de.results": { "...": "..." } }
}
```

The manifest is intentionally self-describing: a run can be inspected without
re-reading R logs, and a future scheduler can rebuild a graph from
`graph.json` plus the recorded parameters.

## Design decisions

- **R for statistics, Python for orchestration.** DESeq2/limma/clusterProfiler
  are already installed and battle-tested in `scptools`; re-implementing them
  in Python would add risk. Python is used only for graph, process and HTTP
  plumbing.
- **File-based node contract.** Nodes communicate through files, not in-memory
  objects. This makes each node individually runnable, cacheable and debuggable
  (`task.json` + `result.json` + logs).
- **Ports instead of implicit column names.** Typed ports (`matrix`, `table`,
  `plot`) catch most wiring mistakes before any R process starts.
- **Offline enrichment.** GO via `GO.db` and `org.*.eg.db` avoids network
  flakiness in analysis runs; KEGG/Reactome/MSigDB can be added as optional
  nodes.
- **Server-side data.** The canvas never uploads matrices; nodes read paths on
  the host. This is the right model for the multi-GB proteomics files in this
  workspace.

## Extension guide

To add a node:

1. Add a catalog entry in `omics_canvas/specs/nodes.yaml`.
2. Implement the R function in `r/` and return the standard result list.
3. Add the R file name to `r_file` if it is a new file.
4. Add an example graph and run
   `PYTHONPATH=. python -m omics_canvas validate <graph>`.
5. If the node needs a new parameter type, extend `catalog.Param` and
   `web/app.js`.

To add a frontend, keep the four endpoints `/api/catalog`, `/api/validate`,
`/api/run`, `/api/runs/<id>` and the graph JSON dialect; no Python changes are
needed.

## Known gaps and next steps

- Add long-format loaders for Spectronaut / DIA-NN reports so the 20c and
  One-Tip data can enter the canvas.
- Add batch covariates and multi-factor designs to `prot.de`.
- Add a `prot.load_msnset` node for the existing `MSnBase` objects.
- Add KEGG/Reactome/MSigDB gene sets as optional enrichment nodes.
- Add authentication to the DSH proxy route (the inspector uses
  `ctx.connection.authorizeIndex`); today the route trusts the local network.
- Add a native React canvas panel instead of the iframe if the DSH theme and
  deep-linking become requirements.
- Stream very large report bundles instead of building the ZIP in memory.
