# Override for rna.heatmap: compact paper-style heatmap of all significant DE genes.
rna_heatmap <- function(task) {
  df <- read_tsv_file(input_path(task, "results"))
  mat_df <- read_tsv_file(input_path(task, "matrix"))
  samples <- read_tsv_file(input_path(task, "samples"))
  sample_ids <- as.character(samples$sample_id)
  mat <- df_to_matrix(mat_df, "gene_id", sample_ids)
  group_col <- resolve_group_column(samples, task, "group")

  padj_cutoff <- p_num(task, "padj_cutoff", 0.05)
  lfc_cutoff <- p_num(task, "lfc_cutoff", 0)
  only_sig <- p_bool(task, "only_significant", TRUE)
  stat_col <- if ("stat" %in% names(df)) "stat" else "log2FoldChange"

  if (!"padj" %in% names(df)) stop("The DE table has no padj column.")
  df <- df[!is.na(df$padj), , drop = FALSE]
  if (isTRUE(only_sig)) {
    df <- df[df$padj < padj_cutoff, , drop = FALSE]
  }
  if (is.finite(lfc_cutoff) && lfc_cutoff > 0 && "log2FoldChange" %in% names(df)) {
    df <- df[!is.na(df$log2FoldChange) & abs(df$log2FoldChange) >= lfc_cutoff, , drop = FALSE]
  }
  if (nrow(df) == 0) stop("No genes passed the heatmap thresholds.")
  df <- df[order(df[[stat_col]], decreasing = TRUE, na.last = TRUE), , drop = FALSE]
  df <- df[!duplicated(df$gene_id), , drop = FALSE]

  feature_ids <- read_feature_list(task)
  if (length(feature_ids)) {
    keep <- df$gene_id %in% feature_ids
    if ("gene_symbol" %in% names(df)) keep <- keep | df$gene_symbol %in% feature_ids
    df <- df[keep, , drop = FALSE]
    if (nrow(df) == 0) stop("None of the requested genes were found.")
  } else if (!isTRUE(only_sig)) {
    top_n <- p_int(task, "top_n", 50)
    df <- df[seq_len(min(top_n, nrow(df))), , drop = FALSE]
  }

  genes <- intersect(as.character(df$gene_id), rownames(mat))
  if (length(genes) < 2) stop("Fewer than two selected genes are present in the matrix.")
  df <- df[match(genes, as.character(df$gene_id)), , drop = FALSE]
  m <- mat[genes, , drop = FALSE]

  meta <- as.data.frame(samples, stringsAsFactors = FALSE)
  meta <- meta[match(colnames(m), as.character(meta$sample_id)), , drop = FALSE]
  groups <- as.character(meta[[group_col]])
  if (anyNA(groups)) stop("Sample sheet has missing group values.")
  group_levels <- unique(groups)
  if (all(c("non_foam", "foam") %in% group_levels)) {
    group_levels <- c("non_foam", setdiff(group_levels, "non_foam"))
  }
  groups <- factor(groups, levels = group_levels)
  ord <- order(groups, colnames(m))
  m <- m[, ord, drop = FALSE]
  groups <- groups[ord]

  scale_method <- tolower(p_str(task, "scale_method", "minmax"))
  if (identical(scale_method, "zscore")) {
    m_scaled <- zscore_rows(m)
  } else {
    m_scaled <- t(apply(m, 1, function(x) {
      rg <- diff(range(x, na.rm = TRUE))
      if (!is.finite(rg) || rg == 0) rep(0.5, length(x)) else (x - min(x, na.rm = TRUE)) / rg
    }))
  }
  labels <- if ("gene_symbol" %in% names(df)) as.character(df$gene_symbol) else genes
  labels[is.na(labels) | !nzchar(labels)] <- genes[is.na(labels) | !nzchar(labels)]
  rownames(m_scaled) <- make.unique(labels)

  color_low <- p_str(task, "color_low", "#3B5998")
  color_high <- p_str(task, "color_high", "#E42528")
  col_fun <- circlize::colorRamp2(c(0, 0.5, 1), c(color_low, "#F0F0F0", color_high))

  counts <- table(groups)
  col_labels <- sprintf("%s\n(n=%d)", levels(groups), as.integer(counts[levels(groups)]))
  col_split <- factor(groups, levels = levels(groups), labels = col_labels)

  width <- p_num(task, "width", 0)
  height <- p_num(task, "height", 0)
  if (!is.finite(width) || width <= 0) width <- max(4.6, 0.45 * ncol(m_scaled) + 3)
  if (!is.finite(height) || height <= 0) height <- min(10, max(5, 0.12 * nrow(m_scaled) + 2.5))

  ht <- ComplexHeatmap::Heatmap(
    m_scaled,
    name = "Row-scaled",
    col = col_fun,
    cluster_rows = p_bool(task, "cluster_rows", FALSE),
    cluster_columns = p_bool(task, "cluster_columns", FALSE),
    show_row_names = p_bool(task, "show_row_names", FALSE),
    show_column_names = FALSE,
    column_split = col_split,
    column_gap = grid::unit(0.5, "mm"),
    column_title_gp = grid::gpar(fontsize = 12),
    row_names_gp = grid::gpar(fontface = "italic", fontsize = 7),
    use_raster = FALSE,
    heatmap_legend_param = list(
      title = NULL,
      at = c(0, 0.5, 1),
      labels = c("Row min", "Row mid", "Row max"),
      direction = "horizontal",
      legend_width = grid::unit(3.6, "cm")
    )
  )

  outdir <- task$outdir
  gene_table <- data.frame(
    gene_id = genes,
    gene_symbol = labels,
    stat = if (stat_col %in% names(df)) df[[stat_col]] else NA_real_,
    log2FC = if ("log2FoldChange" %in% names(df)) df$log2FoldChange else NA_real_,
    padj = df$padj,
    stringsAsFactors = FALSE
  )
  write_tsv_file(gene_table, file.path(outdir, "heatmap_genes.tsv"))
  plot_art <- save_heatmap(
    ht, outdir, "heatmap",
    width = width, height = height, legend_side = "bottom",
    padding = grid::unit(c(10, 4, 12, 4), "mm")
  )
  list(
    ok = TRUE,
    artifacts = list(
      plot = plot_art,
      genes = artifact(outdir, "heatmap_genes.tsv", "table", "Selected genes")
    ),
    metrics = list(n_features = nrow(m_scaled), n_samples = ncol(m_scaled), scale = scale_method),
    messages = sprintf("Selected %d genes (padj < %.3g, lfc >= %.3g).",
                       nrow(m_scaled), padj_cutoff, lfc_cutoff)
  )
}
