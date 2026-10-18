# Project resources and data inventory

This page records what in the SCP workspace is directly usable by Omics Canvas,
what is ready but not yet wired, and what is research material rather than an
analysis input. Paths are relative to the workspace root
`/home/wlt2025/project/SCP`.

## Runtime environment

`scptools` is the intended environment and already contains everything used by
the shipped nodes.

| Item | Observed value |
|---|---|
| Conda environment | `scptools` |
| R | 4.5.3 |
| Installed R packages | 475 |
| Python | 3.12.13 (inside `scptools`) |
| Python packages used | `PyYAML`; the R bridge only needs `Rscript` |
| Rscript path | `/home/wlt2025/anaconda3/envs/scptools/bin/Rscript` |

Key R packages present: `DESeq2`, `limma`, `edgeR`, `clusterProfiler`, `fgsea`,
`ComplexHeatmap`, `circlize`, `MSnbase`, `preprocessCore`, `impute`,
`org.Mm.eg.db`, `org.Hs.eg.db`, `GO.db`, `ggplot2`, `ggrepel`, `patchwork`,
`enrichplot`, `pcaMethods`, `vsn`, `sva`.

## Directly wired into the two examples

### 1. Bulk RNA-seq — GSE116271 (foam vs non-foam macrophages)

Source: GEO GSE116271, Kim et al., *Circulation* 2018; sorted atherosclerotic
lesion macrophages, 3 foam and 3 non-foam samples, mouse (GRCm38, Ensembl 76).

| Asset | Path | Notes |
|---|---|---|
| Per-sample raw tables | `scp_CAD/public_data/GSE116271_RAW/bulkRNA-seq/GSM3215429…GSM3215434_*_gene_counts.txt.gz` | 6 files; columns `Feature/Chr/Start/End/Strand/Length/Count/CPM/RPKM` |
| Analysis-ready counts | `scp_CAD/res/txt/GSE116271_bulk_2026-10-15/counts_matrix.tsv` | 41,388 genes × 6 samples, integer counts, `gene_id/gene_symbol/gene_biotype` columns |
| Sample sheet | `scp_CAD/res/txt/GSE116271_bulk_2026-10-15/samples.tsv` | `sample_id`, `gsm`, `group`, `file_path` |
| Gene annotation | `scp_CAD/res/txt/GSE116271_bulk_2026-10-15/gene_anno.tsv` | symbol, biotype, coordinates, length |
| Ensembl r76 GTF | `scp_CAD/genesets/GRCm38.v76.gtf.rds` | `GRanges`, 41,388 gene records |
| ID alias supplement | `scp_CAD/data/gene_id_aliases/ensembl_r76_rest_supplement_20261015.tsv` | fallback IDs |
| Existing DESeq2 results | `scp_CAD/res/txt/GSE116271_bulk_2026-10-15/de_nonfoam_vs_foam_*.tsv` | useful as a correctness reference |
| Upstream script | `scp_CAD/code/r/SCP_CAD_step0_pubBulkRNAseq_20261015.R` | shows the original DESeq2 / GSEA workflow |

The canvas example `rna_seq_gse116271.json` starts from `counts_matrix.tsv` and
`samples.tsv`; everything downstream is recomputed by the plugin. The original
processing retained 11,329 genes after the ≥10-count-in-≥3-samples filter and
reported 1,168 genes at FDR < 0.05 (525 up in foam, 643 up in non-foam). The
plugin uses the same pre-filter and reports 858 genes when the additional
|log2FC| ≥ 1 cutoff is applied; the full result table covers the same 11,329
tested genes.

### 2. Bulk proteomics — PXD046756

| Asset | Path | Notes |
|---|---|---|
| MaxQuant proteinGroups | `scp_AD/data/CR_2024/PXD046756/proteinGroups.txt` | 10,737 protein groups; 10 samples: `BV2-1..3`, `exMM1..4`, `vitroMM1..3`; mouse |
| Copy-number table | `scp_AD/data/CR_2024/PXD046756/proteinGroups_copyNumbers.csv` | optional downstream annotation |
| Upstream preprocessing script | `scp_AD/code/r/SCP_AD_pub_bulk_proteomics..R` | MaxQuant filtering and MSnSet construction |

The file has `Reverse`, `Potential contaminant` and `Only identified by site`
flags near the end, and per-sample columns named `Intensity <sample>`. The
canvas example `bulk_proteomics_pxd046756.json` parses the file, removes
decoys/contaminants, extracts `Intensity`, filters proteins quantified in at
least 50% of samples, log2-transforms, median-normalizes, imputes with MinProb
and tests `exMM vs BV2` with limma.

## Ready but not wired into the default examples

### Human MaxQuant dataset — PXD046765

`scp_AD/data/CR_2024/PXD046765/proteinGroups.txt` has 10,771 protein groups and
11 samples (`hESC1..3`, `MG482/485/486/877`, `RM227`, `Xplant1..2`), human.
It can be used by the same `prot.load_maxquant` node with
`intensity_type: Intensity`; set `organism: human` on the enrichment nodes.

### Preprocessed bulk protein MSnSet

`scp_AD/res/r_obj/SCP_bulk_protein_CR2024_20260706.rds` (1.5 MB) is an
`MSnSet` with 10,877 proteins × 21 samples, already log2-scale (`exprs` range
0–12.06), with `pData` columns `id`, `prefix`, `group`, `species`,
`MeasurementName`. This is a convenient starting point for a future
`prot.load_msnset` node; today the plugin starts one step earlier, from
MaxQuant output.

### Single-cell proteomics (SCP) data

| Asset | Path | Notes |
|---|---|---|
| 20c Spectronaut report | `scp_AD/data/20260701_20c_summary/20260630_20c_Report_SCP_Report_Normal (Normal).tsv` | 3.4 GB, 95 columns, long format (`R.FileName`, `PG.*`, `PEP.*`, `EG.*`, `FG.*`) |
| 20c MSnSet | `scp_AD/res/r_obj/SCP_20c_eda_msnbase_20260706.rds` | 4.7 MB, ready for protein-level QC |
| SCP reports in scp_CAD | `scp_CAD/data/202607_/*_Report.tsv`, `scp_CAD/data/20260808/*`, `scp_CAD/data/20260915/*` | 2–15 GB each, Spectronaut-style long reports |
| Column-specific libraries | `scp_CAD/data/20c_lib/`, `scp_CAD/data/test_Column_Specific_SuperLibraries/` | ~0.4–0.65 GB per library |

These are long-format reports rather than protein × sample matrices. A future
`prot.load_report` node would need to parse `R.FileName`, `PG.ProteinGroups`,
`PG.Genes` and `PG.Quantity` (or `PG.Log2Quantity`) and pivot to a matrix. The
existing `scp_AD` scripts show the required metadata parsing.

### DIA single-cell proteomics and simulation code

| Asset | Path | Notes |
|---|---|---|
| One-Tip raw files | `flowscp/data/onetip/raw/` | 31 Thermo Astral `.raw` files, ~7 GB each |
| One-Tip DIA-NN output | `flowscp/data/onetip/DIA-NN/report.tsv` | 1.4 GB, long format; `*_matrix.tsv` files are pre-pivoted |
| One-Tip first pass | `flowscp/data/onetip/DIA-NN/report-first-pass.tsv` | 1.2 GB |
| HeLa dia-PASEF | `flowscp/data/HeLa_Evosep_diaPASEF/` | Bruker `.d` runs (not inspected in this pass) |
| Contaminant FASTA | `flowscp/data/reference_database/contaminants_for_Spectronaut_ziluye.fasta` | 153 KB |
| DIA simulation / noise model | `flowscp/flowscp/simulation/`, `flowscp/flowscp/processing/`, `flowscp/flowscp/real_data/` | Python modules for digestion, chromatography, DIA, noise-aware FDR, MBR |
| Mirror implementation | `demo_dia/` | Earlier copy of the same pipeline with runnable demo |

`flowscp` is the place to look for noise-aware FDR, denoising and MBR logic. It
is not yet connected to the canvas; the current `prot.*` nodes cover the
conventional bulk MaxQuant → limma path.

### Single-cell RNA-seq count matrices

`scp_AD/data/pub_scRNA-seq/APP_scRNAseq_CR_2020/` contains six 10x-style
datasets (`APP_IL33_1/2`, `APP_Con_1/2`, `WT_Con_1/2`) with
`barcodes.tsv.gz`, `features.tsv.gz`, `matrix.mtx.gz` (~283 MB total). These are
single-cell matrices, not bulk, so they are not compatible with `rna.load_matrix`
without pseudobulking. They are relevant to a future single-cell branch of the
canvas.

## Additional research assets (not analysis inputs for this plugin)

| Asset | Path | Why it matters |
|---|---|---|
| AlphaDIA | `study/alphadia/` | Alternative DIA search engine, Python workflow code |
| AlphaPeptDeep | `study/alphapeptdeep/`, `study/alpha_tutorial/` | RT/CCS/MS2 prediction models and tutorials |
| ProteomicsVisualization | `study/ProteomicsVisualization/` | Notebooks for precursor/peptide/protein visualization |
| Brain multi-omics | `study/nbt_brain/` | `RNA_modality.h5ad` (2 GB), `protein_modality.h5ad` (12 MB), PRIDE reports |
| 20c libraries | `study/from_zhr/` | Column-specific super-libraries (~0.7 GB each) |
| Large archives | `datasets/alphapeptdeep_notebooks_and_data.zip` (6.6 GB), `datasets/libfree-gui-v1.10.1.zip` (19 GB), `datasets/transfer-dimethyl-v1.8.1.zip` (22 GB) | Offline packages/data, not needed for the current nodes |
| Method papers | `references/*.pdf` | One-Tip and Chip-Tip single-cell proteomics methods |

## Practical caveats

- **Server-side paths.** The canvas never uploads data; nodes read paths on the
  machine running the R process. For a remote deployment, mount the data and
  run the server next to it.
- **Size.** The 20c report (3.4 GB), DIA-NN report (1.4 GB) and raw files
  (hundreds of GB) are not appropriate for browser-side parsing; a dedicated
  loader node should stream or pre-pivot them.
- **Species and annotation.** Mouse examples use `org.Mm.eg.db`; human PXD046765
  needs `organism: human` (`org.Hs.eg.db`).
- **Zeros vs missing.** MaxQuant writes `0` for missing intensities; the
  `prot.filter` node converts zeros to `NA` before filtering and imputation.
  Tune `min_valid_frac` and the imputation method; aggressive imputation can
  inflate the number of differential proteins.
- **Gene IDs.** GSE116271 uses Ensembl release 76 IDs; the symbol columns in the
  processed matrix are the stable join key for enrichment.
- **Reproducibility.** Every run records `graph.json`, per-node params in
  `manifest.json`, R logs and artifact paths. Runs can be resumed with
  `--resume`.
