# Implementation status

As of 2026-10-19, the merged `dsh-omics-canvas` package is installed in the
DSH `web` profile, the sidebar panel is enabled, and the standalone server is
stopped. The Python child is managed by the DSH plugin.

## Plan checklist

| Plan item | Status | Evidence |
|---|---|---|
| DSH bundle, sidebar panel, `/omics-canvas` proxy | Done | `package.json`, `src/index.js`, `client/client.js`; `/omics-canvas/` returns 200 |
| `omics_canvas_*` agent tools | Done | 14 tools in `src/index.js`; fake-context harness asserts `parameters.type === "object"` |
| Tool schema compatibility fix | Done | explicit JSON Schema `type: "object"` for every tool |
| Custom R nodes | Done | `omics_canvas/specs/custom_nodes/*.json`, `r/custom/*.R` |
| Custom Python nodes | Done | `py/custom/*.py`, `py/dispatch.py`, `py/common.py` |
| Edit code for every node | Done | inspector code editor; `r/overrides/<type>.R`; API `GET/PUT/DELETE /api/nodes/<type>/code` |
| Code validation before save | Done | `Rscript parse()` for R; `compile()` for Python |
| Per-node conda environment | Done | graph `env`; `/api/environments`; inspector dropdown; cache key includes env |
| Clone a built-in node's ports as a custom node | Done | inspector action “Clone ports as custom” (ports/params + template; built-in logic is not copied) |
| Per-node timing and run timing | Done | `duration_s`, `total_duration_s`, `wall_duration_s`, `slowest_node` |
| Content-addressed cache | Done | `omics_canvas/cache.py`; repeat runs show `cache_hit: true` |
| Cache stats / clear | Done | `/api/cache`, `omics_canvas cache stats|clear`, Results drawer |
| Publication HTML report | Done | graph SVG, methods, timings, cache, figures, table previews |
| Reproducible ZIP bundle | Done | `report.html`, `graph.svg`, `code/<node>.R|.py`, `run_all.sh`, `README.md`, artifacts |
| Artifact browsing | Done | Results drawer, image preview, table preview, downloads, per-node logs |
| Canvas chat bridge | Done | Chat drawer → `postMessage` → current DSH session; replies in DSH conversation |
| Edit selected node with agent | Done | canvas document API, `omics_canvas_get_canvas` / `omics_canvas_patch_canvas`, 3 s browser poll |
| Built-in code visible/editable | Done | `read_node_code` extracts the actual R function; saving writes an override |
| Heatmap customization params | Done | feature list, clustering, row labels, z cap, colors, width/height |
| KEGG GSEA node | Done | `rna.gsea_kegg`: significant genes, Ensembl→ENTREZ mapping with symbol fallback, `gseKEGG(mmu/hsa)`, table + dot plot + heatmap with running-ES panels and bottom color bar |
| GO GSEA kept separate | Done | `rna.enrich_gsea` remains the offline GO alternative |
| Canvas Chinese/English switch | Deferred/cut | Language toggle removed; English UI only for now |
| Tests | Done | `pytest` 24 passed; Playwright UI checks; fake-context tool smoke |
| Documentation | Done | `README.md`, `README.dsh.md`, `docs/architecture.md`, this file |
| Cleanup | Done | test runs/cache entries removed; standalone stopped |

## Partially verified

- **Real-model conversation**: the tools are registered and call the real
  server, but no scripted model transcript is retained in the repository. The
  tool layer is verified with a fake host context; a live DSH conversation
  should be smoke-tested after a restart.
- **Tool declarations in the running DSH**: the running profile imports the
  bundle and the HTTP proxy works. The JSON Schema fix requires the Host module
  to be reloaded; restart `dsh web` once if an old schema error persists.

## Not implemented / deliberate gaps

- Auth gate on `/omics-canvas` (the route trusts the local network; the
  inspector uses DSH's `authorizeIndex`, this plugin does not yet).
- Native React canvas panel; the DSH panel remains a same-origin iframe.
- DOCX/PDF generation; the HTML report is print-to-PDF ready.
- Multi-factor designs beyond the RNA-seq `design_formula`, and proteomics
  batch covariates.
- Spectronaut / DIA-NN long-format loaders; only MaxQuant and matrices are
  wired today.
- Automatic LLM planning inside the canvas; intelligence comes from the DSH
  agent calling the tools.

## How “intelligent” works

The canvas is a deterministic execution engine. The intelligence is the DSH
agent:

1. The model reads the request.
2. `omics_canvas_catalog` exposes node types, ports and parameter schemas.
3. The model constructs a graph and calls `omics_canvas_validate`.
4. `omics_canvas_run` executes it; `omics_canvas_status` reports progress,
   timing, cache and artifacts.
5. `omics_canvas_upsert_node` / `omics_canvas_node_code` let the agent add or
   edit R/Python nodes; `omics_canvas_read_artifact` and
   `omics_canvas_export_run` close the loop.

Graph validation, typed ports, syntax checks and cache keys constrain the
model's output, so a bad graph fails loudly instead of silently producing
wrong results.
