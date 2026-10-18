# Omics Canvas

[English](README.md) | **中文**

一个面向**组学分析**的画布式节点图插件。计算图引擎是通用的；仓库自带两条 bulk 端到端示例，直接运行在本工作区已有的真实数据上：

- **Bulk RNA-seq** — 表达矩阵 → 过滤 → 归一化 → PCA → DESeq2 → 火山图 / 热图 → GO 过表达 / GO 或 KEGG GSEA。
- **Bulk 蛋白组** — MaxQuant `proteinGroups.txt` → 过滤 → log2 与归一化 → 缺失值填补 → PCA → limma → 火山图 / 热图 → GO 过表达。

每个节点都由 `scptools` conda 环境中的 R 或 Python 执行（单节点也可选择其他 conda 环境）。画布是零依赖的浏览器编辑器；同一张图也可以在命令行无头运行，DSH 智能体则可以通过工具构建和运行计算图。

![画布编辑器](docs/canvas-default.png)

## 设计哲学

生信与组学分析并不是标准化的自动化场景。每个研究都围绕不同的科学问题定制流程，这种定制带来的是响应速度和贴合度；但定制的代价会滞后出现：脚本、参数、图和一次性环境不断累积，后续的管理、审查、维护与更新往往由另一个人承担。

这里的策略，是把分析还原为**计算图**，把每一步还原为**计算节点**。计算图让分析显式、可审查；计算节点让步骤可复用、可替换。早期的云平台和图系统也追求同一抽象，但它们的图与节点维护成本很高：增加一步、调整一个参数或采用一种新方法，常常意味着修改平台代码、重新部署或复制一份工作流。

本插件让计算图和节点同时具备**智能体可编辑**与**用户可编辑**能力。智能体可以从节点目录组装计算图、改写节点参数或实现、校验结果、运行并检查产物；画布则把这些操作直接暴露给用户。计算图是契约，智能体（或用户）是编辑器，节点是复用单元。

一旦分析固定下来，计算图就固定下来。代码和函数可以跨项目复用，同一张图可以在新的组学数据上重跑；复现不再依赖口口相传的脚本，而是显式的计算图，连同输入、参数、环境和缓存产物。

## 在 DSH 中安装与使用

本包是一个完整的 DSH bundle。在工作区根目录执行：

```bash
dsh plugin --profile web add /path/to/dsh-omics-canvas
```

刷新 DSH Web 页面，打开 **Plugins**，确认 **Omics Canvas** 处于 **On**。侧边栏入口会打开画布。若修改过 Host 代码，需要重启一次正在运行的 `dsh web`，让新的工具声明和 Python 子进程加载。详细说明、智能体示例与排错见 [README.dsh.md](README.dsh.md)。

## 功能

- 19 个内置 bulk RNA-seq / 蛋白组节点，另有自定义 R / Python 节点。
- 每个节点都可编辑代码，内置节点以 override 方式保存；保存前会做语法检查，避免覆盖可工作的实现。
- 每个节点可选择 conda 环境。
- 每个节点记录耗时；内容寻址的结果缓存，支持缓存统计与清空。
- 自包含 HTML 发表报告，以及每个节点一份代码 driver 的 ZIP 代码包。
- 14 个 `omics_canvas_*` 工具，用于对话式构图、节点编辑与运行。
- 画布内 **Chat** 抽屉可把 prompt 发给当前 DSH 会话；回复显示在 DSH 对话中（抽屉内有 “Open DSH conversation” 链接）。

## 快速开始

```bash
conda activate scptools
cd /path/to/dsh-omics-canvas

# 浏览器画布 + 本地运行 API（workdir = 工作区根目录）
PYTHONPATH=. python -m omics_canvas serve --workdir /path/to/workspace
# 打开 http://127.0.0.1:8765/
```

无头运行（在画布包根目录执行，示例中的相对路径由 `--workdir` 解析）。随包示例使用的是作者工作区的数据路径，运行前请把 `expression` / `sample_sheet` 改成你自己的数据：

```bash
cd /path/to/dsh-omics-canvas
PYTHONPATH=. python -m omics_canvas run \
  omics_canvas/specs/examples/rna_seq_gse116271.json \
  --workdir /path/to/workspace

PYTHONPATH=. python -m omics_canvas run \
  omics_canvas/specs/examples/bulk_proteomics_pxd046756.json \
  --workdir /path/to/workspace
```

其他命令：

```bash
PYTHONPATH=. python -m omics_canvas list
PYTHONPATH=. python -m omics_canvas validate <graph.json>
PYTHONPATH=. python -m omics_canvas runs
PYTHONPATH=. python -m omics_canvas show <run_id>
```

`run` 支持 `--target <node_id…>`（只运行某节点的祖先）、`--resume`（继续中断的运行）和 `--run-dir`（复用固定目录）。

## 节点目录

| 类别 | 节点 | 用途 |
|---|---|---|
| RNA-seq | `rna.load_matrix` | 读取基因 × 样本矩阵，可选样本表 |
| RNA-seq | `rna.filter` | 按 count/CPM 阈值保留基因 |
| RNA-seq | `rna.normalize` | VST、rlog、log-CPM、TMM 或 log2 |
| RNA-seq | `rna.pca` | 高变基因 PCA |
| RNA-seq | `rna.de` | 单对比 DESeq2 Wald 检验 |
| RNA-seq | `rna.volcano` | 火山图 |
| RNA-seq | `rna.heatmap` | Top 差异基因的行标准化热图 |
| RNA-seq | `rna.enrich_ora` | GO 过表达（`org.Mm.eg.db` / `org.Hs.eg.db`） |
| RNA-seq | `rna.enrich_gsea` | 基于 DESeq2 statistic 的 GO 基因集富集 |
| RNA-seq | `rna.gsea_kegg` | 显著基因 KEGG GSEA：表、通路 dot plot、带 running-ES 双面板的热图 |
| 蛋白组 | `prot.load_maxquant` | 解析 MaxQuant proteinGroups，去除 decoy/contaminant |
| 蛋白组 | `prot.filter` | 0 → 缺失，按有效值/肽段数过滤 |
| 蛋白组 | `prot.transform` | log2 与 median / quantile 归一化 |
| 蛋白组 | `prot.impute` | MinProb、MinDet 或 kNN 填补 |
| 蛋白组 | `prot.pca` | 填补后蛋白矩阵 PCA |
| 蛋白组 | `prot.de` | limma moderated t-test |
| 蛋白组 | `prot.volcano` | 火山图 |
| 蛋白组 | `prot.heatmap` | Top 蛋白的行标准化热图 |
| 蛋白组 | `prot.enrich_ora` | 基于 MaxQuant gene names 的 GO 过表达 |

GO 富集节点可离线运行：使用 `GO.db` 和对应物种的注释包。`rna.gsea_kegg` 使用 `clusterProfiler::gseKEGG`，并从 `rest.kegg.jp` 读取 KEGG 通路注释，因此需要网络（或已填充的 KEGG 缓存）。

热图节点直接暴露 `feature_list`、行/列聚类、行名、`z_cap`、低/高颜色和输出尺寸。Inspector 还会加载真实的内置实现（例如 `rna_heatmap <- function(task)`），保存时写入 override；参数覆盖不到的部分可以直接改代码，或让智能体改。

## 输出

每次运行写入 `runs/<timestamp>_<slug>/`：

```text
runs/20261018_231806_rna-seq-gse116271-foam-vs-non-foam/
├── manifest.json          # 运行状态、节点状态、指标、产物索引
├── graph.json             # 实际执行的计算图
├── logs/<node>.log        # 每个节点的 R stdout/stderr
└── <node>/                # task.json、result.json、表格与 PNG/PDF 图
```

`manifest.json` 是 UI 的唯一事实来源：记录每个节点的状态、耗时、缓存命中/键、参数、消息、指标和产物 URL，也记录 `total_duration_s`（节点耗时之和）、`wall_duration_s`、`slowest_node` 和缓存摘要。画布提供的产物链接形如 `/api/runs/<run_id>/files/<node>/<file>`。

每次运行还提供：

- `GET /api/runs/<id>/report` — 自包含 HTML 报告（计算图 SVG、图、表预览、方法、耗时、缓存）。
- `GET /api/runs/<id>/export` — ZIP 代码包，包含 `report.html`、`graph.svg`、每个节点一份 `code/<node>.R` 或 `code/<node>.py`、`run_all.sh`、`README.md` 及全部产物。

## 画布编辑器

- 点击左侧节点库中的节点加入画布。
- 拖动节点标题移动节点；拖动空白处平移；滚轮缩放。
- 从右侧输出端口拖到左侧输入端口即可连线。
- 选中节点后，在右侧 Inspector 编辑参数。
- `Run canvas` 执行计算图并按状态给节点着色；节点完成后，产物（包括 PNG 图）出现在 Inspector 中。
- `Previous runs` 重新加载已完成运行的图、状态和产物，但不会重新执行。
- `Export` / `Import` 以 JSON 交换计算图；最新图也会保存在浏览器 `localStorage` 中。

编辑器与 API 默认绑定 `127.0.0.1`。只有在可信网络中才使用 `--host 0.0.0.0`。

## 计算图格式

```json
{
  "name": "RNA-seq example",
  "nodes": [
    {
      "id": "load",
      "type": "rna.load_matrix",
      "x": 40,
      "y": 260,
      "params": {
        "expression": "scp_CAD/res/txt/GSE116271_bulk_2026-10-15/counts_matrix.tsv",
        "sample_sheet": "scp_CAD/res/txt/GSE116271_bulk_2026-10-15/samples.tsv"
      }
    }
  ],
  "edges": [
    {"from": "load", "from_port": "expr", "to": "filter", "to_port": "expr"}
  ]
}
```

- `nodes[].id` 必须唯一。
- `edges[].from_port` / `to_port` 必须存在于节点目录中，且类型一致（`matrix`、`table`、`plot`）。
- 每个输入端口最多接受一条边。
- 计算图必须无环。

## 自定义节点与代码编辑

每个节点在 Inspector 中都有可编辑的代码区：

- **内置节点**加载真实的内置实现（例如 `rna_heatmap <- function(task)`）。保存会写入 `r/overrides/<node_id>.R`，不改动随包发布的源码；`Reset override` 可移除 override。
- **自定义节点**是完整的用户节点，支持 **R 或 Python**。`+ New` 打开对话框，填写 id（`custom.*`）、语言、标题、端口（`id:type`）、参数 JSON 和代码。R 节点写入 `r/custom/<id>.R`，Python 节点写入 `py/custom/<id>.py`，并在 `specs/custom_nodes/<id>.json` 中声明。
- **校验**：R 用 `Rscript parse()`，Python 用 `compile()`，通过后才替换文件，避免坏代码覆盖可用节点。
- **运行环境**可在 Inspector 中按节点选择。默认值来自服务端/插件配置（`scptools`）；下拉框列出 `GET /api/environments` 返回的 conda 环境。R 和 Python 节点都在所选环境中运行，环境也参与缓存键。
- **智能体路径**：`omics_canvas_upsert_node`、`omics_canvas_node_code`、`omics_canvas_delete_node` 和 `omics_canvas_reset_node_code` 覆盖同样的操作。

R 自定义代码接收 `task$params`、`task$inputs` 和 `task$outdir`；Python 自定义代码接收同名字典（`task["params"]`、`task["inputs"]`、`task["outdir"]`），并可使用 `from common import write_table`。两者都必须返回：

```r
list(
  ok = TRUE,
  artifacts = list(port = list(file = "file.tsv", type = "table", label = "Label")),
  metrics = list(n = 1),
  messages = character()
)
```

端口类型为 `matrix`、`table`、`plot` 或 `any`；`any` 可连接任意类型。Python 节点由 `py/dispatch.py` 调度：导入节点模块并调用 `run(task)`。

## 计时与结果缓存

- 每个节点记录 `started_at`、`finished_at`、`duration_s`；运行记录 wall time 和最慢节点。
- 节点结果按内容寻址键缓存：节点类型、解析后的参数、输入文件内容、节点源码/override、`common.R` 与 `dispatch.R` 哈希，以及 R 环境。
- 缓存命中时，把缓存产物复制到新运行目录并跳过 R 进程；节点标记为 `cached`。
- CLI：`--no-cache`、`--cache-dir`，以及 `omics_canvas cache stats|clear`。
- API：`GET /api/cache`、`DELETE /api/cache`。
- UI 在运行横幅显示缓存命中，在 Inspector 显示 `cached` 标记，在 Results 抽屉中提供缓存统计与清空。

## DSH 工具

画布作为 DSH bundle 挂载后，Host 暴露：

| 工具 | 用途 |
|---|---|
| `omics_canvas_catalog` | 列出节点类型、端口和参数 schema |
| `omics_canvas_validate` | 校验计算图 |
| `omics_canvas_run` | 启动一次运行 |
| `omics_canvas_status` | 每节点状态、耗时、缓存和产物 |
| `omics_canvas_list_runs` | 列出历史运行 |
| `omics_canvas_upsert_node` | 创建/更新自定义 R 或 Python 节点 |
| `omics_canvas_node_code` | 读取或写入节点代码 |
| `omics_canvas_delete_node` | 删除自定义节点 |
| `omics_canvas_reset_node_code` | 移除内置节点的 override |
| `omics_canvas_get_canvas` | 读取当前打开的画布文档 |
| `omics_canvas_patch_canvas` | 修改画布中的节点参数/连线 |
| `omics_canvas_cache` | 缓存统计 / 清空 |
| `omics_canvas_read_artifact` | 读取文本产物或获取二进制 URL |
| `omics_canvas_export_run` | 报告与代码包 URL |

## 环境与依赖

- `scptools` conda 环境中的 R 4.5.3（已安装 475 个包），包括 `DESeq2`、`limma`、`edgeR`、`clusterProfiler`、`fgsea`、`ComplexHeatmap`、`MSnbase`、`org.Mm.eg.db`、`org.Hs.eg.db`、`GO.db`。
- Python ≥ 3.9，带 `PyYAML`（`scptools` 的 Python 3.12 解释器已具备）。
- R bridge 在首次运行开始时通过 `conda run -n scptools which Rscript` 解析 `Rscript`；可用 `OMICS_CANVAS_RSCRIPT` 覆盖。

## 限制

- 在 DSH 中，Web 画布仍是 iframe；独立服务器除 DSH 代理外没有额外鉴权。请在可信本地网络中使用。
- 自定义节点以宿主用户权限执行任意 R 代码，只应允许可信用户创建/编辑代码。
- 当前差异分析处理单个两组对比。RNA-seq 可通过 `design_formula` 传入多因素设计，蛋白组暂不支持。
- 蛋白组缺失值填补有意保持简单（左删失正态或 kNN），不能替代 `flowscp` 中噪声感知的 MBR 工作。
- GO 富集可离线运行。`rna.gsea_kegg` 从 `rest.kegg.jp` 读取 KEGG 通路注释，需要网络（或已填充的 KEGG 缓存）；Reactome/MSigDB 基因集是后续工作。
- DSH 面板是独立画布的 iframe，而不是原生 React 重写；`web/` 目录和 `/api/*` 端点仍是其他 shell 的集成面。

## DSH 插件

本画布也打包为 DSH bundle，详见 [`README.dsh.md`](README.dsh.md)：它在 DSH Web UI 注册 **Omics Canvas** 侧边栏面板，在私有 loopback 端口启动 Python 服务器，并代理到 `/omics-canvas`。面板是同源 iframe，因此编辑器、运行 API 和产物链接保持不变。

## 文档

- [`docs/project_resources.md`](docs/project_resources.md) — 本工作区可供插件使用的数据与代码清单。
- [`docs/architecture.md`](docs/architecture.md) — 图引擎、节点契约、API 与扩展指南。
- [`docs/implementation_status.md`](docs/implementation_status.md) — 计划清单、已完成项与已知缺口。

## 扩展插件

1. 在 `omics_canvas/specs/nodes.yaml` 增加节点条目，包含 `id`、`title`、`category`、`r_function`、`r_file`、端口和参数。
2. 在 `r/rna_nodes.R`、`r/prot_nodes.R` 或新的 R 文件中实现 `rna_*` / `prot_*`（或新前缀）函数，返回 `list(ok = TRUE, artifacts = ..., metrics = ..., messages = ...)`。
3. 复用 `common.R` 辅助函数（`pca_impl`、`volcano_impl`、`heatmap_impl`、`ora_impl`、`gsea_impl`、`matrix_with_anno` 等）。
4. 在 `omics_canvas/specs/examples/` 增加示例图，并用 `python -m omics_canvas validate` 校验。
