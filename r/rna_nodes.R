# rna_nodes.R -- bulk RNA-seq nodes for Omics Canvas.
# Each function receives the task list (params + input artifact paths) and
# returns a list(ok, artifacts, metrics, messages).

rna_load_matrix <- function(task) {
  path <- p_str(task, "expression")
  if (is.null(path) || !nzchar(path)) stop("Parameter 'expression' is required.")
  if (!file.exists(path)) stop("Expression matrix not found: ", path)

  df <- read_tsv_file(path)
  gene_col <- p_str(task, "gene_column", "gene_id")
  if (!gene_col %in% names(df)) {
    gene_col <- names(df)[1]
  }
  symbol_col <- p_str(task, "symbol_column", "gene_symbol")
  sample_col <- p_str(task, "sample_column", "sample_id")
  group_col <- p_str(task, "group_column", "group")
  matrix_type <- p_str(task, "matrix_type", "counts")
  sample_sheet <- p_str(task, "sample_sheet", "")

  notes <- character()
  if (!is.null(sample_sheet) && nzchar(sample_sheet)) {
    if (!file.exists(sample_sheet)) stop("Sample sheet not found: ", sample_sheet)
    samples <- read_tsv_file(sample_sheet)
    if (!sample_col %in% names(samples)) {
      stop("Sample column not found in sample sheet: ", sample_col)
    }
    ids <- as.character(samples[[sample_col]])
    missing <- setdiff(ids, names(df))
    if (length(missing)) {
      stop("Samples missing from expression matrix: ", paste(missing, collapse = ", "))
    }
    sample_cols <- ids
    if (!group_col %in% names(samples)) {
      samples[[group_col]] <- infer_group(ids)
      notes <- c(notes, sprintf("Group column '%s' inferred from sample names.", group_col))
    }
  } else {
    anno_cols <- unique(c(gene_col, symbol_col, "gene_biotype", "gene_name", "biotype"))
    candidates <- setdiff(names(df), anno_cols)
    sample_cols <- candidates[vapply(df[candidates], is.numeric, logical(1))]
    if (length(sample_cols) == 0) {
      stop("No numeric sample columns detected in the expression matrix.")
    }
    ids <- sample_cols
    samples <- data.frame(sample_id = ids, group = infer_group(ids),
                          stringsAsFactors = FALSE)
    notes <- c(notes, "No sample sheet supplied; groups were inferred from sample names.")
  }

  mat <- as.matrix(df[, sample_cols, drop = FALSE])
  storage.mode(mat) <- "double"
  n_bad <- sum(!is.finite(mat))
  if (n_bad > 0) {
    notes <- c(notes, sprintf("%d non-finite matrix values were set to NA.", n_bad))
    mat[!is.finite(mat)] <- NA
  }
  rownames(mat) <- make.unique(as.character(df[[gene_col]]))

  if (identical(matrix_type, "counts")) {
    if (any(mat < 0, na.rm = TRUE)) stop("Count matrix contains negative values.")
    if (any(abs(mat - round(mat)) > 1e-6, na.rm = TRUE)) {
      notes <- c(notes, "Matrix type is 'counts' but some values are not integers.")
    }
  }

  features <- data.frame(
    gene_id = as.character(df[[gene_col]]),
    stringsAsFactors = FALSE
  )
  if (symbol_col %in% names(df)) {
    features$gene_symbol <- as.character(df[[symbol_col]])
  }
  if ("gene_biotype" %in% names(df)) {
    features$gene_biotype <- as.character(df[["gene_biotype"]])
  }

  if (p_bool(task, "collapse_symbols", FALSE) && "gene_symbol" %in% names(features)) {
    sym <- features$gene_symbol
    keep_rows <- !is.na(sym) & nzchar(sym)
    mat <- mat[keep_rows, , drop = FALSE]
    sym <- sym[keep_rows]
    ord <- order(rowMeans(mat, na.rm = TRUE), decreasing = TRUE)
    keep <- ord[!duplicated(sym[ord])]
    mat <- mat[keep, , drop = FALSE]
    rownames(mat) <- sym[keep]
    features <- data.frame(gene_id = sym[keep], gene_symbol = sym[keep],
                           stringsAsFactors = FALSE)
    notes <- c(notes, sprintf("Collapsed to %d unique gene symbols.", nrow(mat)))
  }

  anno <- features[match(rownames(mat), features$gene_id), , drop = FALSE]
  rownames(anno) <- NULL
  expr_out <- cbind(anno, as.data.frame(mat, check.names = FALSE))

  samples_out <- samples
  names(samples_out)[names(samples_out) == sample_col] <- "sample_id"
  if (group_col != "group" && group_col %in% names(samples_out)) {
    names(samples_out)[names(samples_out) == group_col] <- "group"
  }
  if (!"group" %in% names(samples_out)) {
    samples_out$group <- infer_group(samples_out$sample_id)
  }

  outdir <- task$outdir
  write_tsv_file(expr_out, file.path(outdir, "expr.tsv"))
  write_tsv_file(samples_out, file.path(outdir, "samples.tsv"))
  write_tsv_file(features, file.path(outdir, "features.tsv"))

  list(
    ok = TRUE,
    artifacts = list(
      expr = artifact(outdir, "expr.tsv", "matrix", "Expression matrix"),
      samples = artifact(outdir, "samples.tsv", "table", "Sample sheet"),
      features = artifact(outdir, "features.tsv", "table", "Feature annotation")
    ),
    metrics = list(
      n_genes = nrow(mat),
      n_samples = ncol(mat),
      matrix_type = matrix_type,
      total_counts = sum(mat, na.rm = TRUE)
    ),
    messages = notes
  )
}

rna_filter <- function(task) {
  expr <- read_tsv_file(input_path(task, "expr"))
  samples <- read_tsv_file(input_path(task, "samples"))
  ids <- as.character(samples$sample_id)
  mat <- df_to_matrix(expr, "gene_id", ids)
  anno <- expr[, setdiff(names(expr), c("gene_id", ids)), drop = FALSE]

  min_count <- p_int(task, "min_count", 10)
  min_samples <- p_int(task, "min_samples", 3)
  min_cpm <- p_num(task, "min_cpm", 0)
  min_total <- p_num(task, "min_total", 0)

  lib <- colSums(mat, na.rm = TRUE)
  keep <- rowSums(mat > 0, na.rm = TRUE) >= 1
  if (!is.null(min_count) && min_count > 0) {
    keep <- keep & rowSums(mat >= min_count, na.rm = TRUE) >= min_samples
  }
  if (!is.null(min_cpm) && min_cpm > 0) {
    lib_safe <- ifelse(lib == 0, 1, lib)
    cpm <- sweep(mat, 2, lib_safe, "/") * 1e6
    keep <- keep & rowSums(cpm >= min_cpm, na.rm = TRUE) >= min_samples
  }
  if (!is.null(min_total) && min_total > 0) {
    keep <- keep & rowSums(mat, na.rm = TRUE) >= min_total
  }

  if (sum(keep) < 2) stop("Fewer than two genes pass the filter.")
  mat_keep <- mat[keep, , drop = FALSE]
  anno_keep <- anno[keep, , drop = FALSE]
  out <- matrix_with_anno(rownames(mat_keep), anno_keep, mat_keep, "gene_id")

  outdir <- task$outdir
  write_tsv_file(out, file.path(outdir, "expr_filtered.tsv"))
  write_tsv_file(samples, file.path(outdir, "samples.tsv"))

  summary <- data.frame(
    metric = c("input_genes", "kept_genes", "removed_genes",
               "min_count", "min_samples", "min_cpm", "min_total"),
    value = c(nrow(mat), nrow(mat_keep), nrow(mat) - nrow(mat_keep),
              min_count %||% 0, min_samples %||% 0, min_cpm %||% 0, min_total %||% 0)
  )
  write_tsv_file(summary, file.path(outdir, "filter_summary.tsv"))

  lib_df <- data.frame(sample_id = ids, library_size = as.numeric(lib),
                       stringsAsFactors = FALSE)
  lib_df$sample_id <- factor(lib_df$sample_id, levels = ids)
  p <- ggplot2::ggplot(lib_df, ggplot2::aes(x = sample_id, y = library_size)) +
    ggplot2::geom_col(fill = "#2563eb", width = 0.7) +
    ggplot2::labs(x = NULL, y = "Library size (sum of values)", title = "Library sizes") +
    ggplot2::theme_bw(base_size = 12) +
    ggplot2::theme(axis.text.x = ggplot2::element_text(angle = 45, hjust = 1))
  plot_art <- save_plot(p, outdir, "library_sizes", width = 6, height = 4)

  list(
    ok = TRUE,
    artifacts = list(
      expr = artifact(outdir, "expr_filtered.tsv", "matrix", "Filtered expression matrix"),
      samples = artifact(outdir, "samples.tsv", "table", "Sample sheet"),
      summary = artifact(outdir, "filter_summary.tsv", "table", "Filter summary"),
      plot = plot_art
    ),
    metrics = list(
      n_input = nrow(mat),
      n_kept = nrow(mat_keep),
      pct_kept = round(100 * nrow(mat_keep) / nrow(mat), 2)
    ),
    messages = sprintf("Kept %d of %d genes.", nrow(mat_keep), nrow(mat))
  )
}

rna_normalize <- function(task) {
  expr <- read_tsv_file(input_path(task, "expr"))
  samples <- read_tsv_file(input_path(task, "samples"))
  ids <- as.character(samples$sample_id)
  mat <- df_to_matrix(expr, "gene_id", ids)
  anno <- expr[, setdiff(names(expr), c("gene_id", ids)), drop = FALSE]

  method <- p_str(task, "method", "vst")
  blind <- p_bool(task, "blind", TRUE)
  notes <- character()
  factors <- NULL

  if (method %in% c("vst", "rlog")) {
    if (!requireNamespace("DESeq2", quietly = TRUE)) {
      stop("DESeq2 is required for method '", method, "'.")
    }
    counts <- round(mat)
    counts[is.na(counts)] <- 0
    if (any(counts < 0)) stop("Counts must be non-negative for VST/rlog.")
    col_data <- data.frame(
      group = factor(as.character(samples$group)),
      row.names = ids
    )
    dds <- DESeq2::DESeqDataSetFromMatrix(
      countData = counts,
      colData = col_data,
      design = ~ 1
    )
    norm <- tryCatch(
      {
        transformed <- if (identical(method, "vst")) {
          DESeq2::vst(dds, blind = blind)
        } else {
          DESeq2::rlog(dds, blind = blind)
        }
        factors <- DESeq2::sizeFactors(transformed)
        SummarizedExperiment::assay(transformed)
      },
      error = function(e) {
        notes <<- c(notes, paste0(method, " failed (", conditionMessage(e),
                                  "); fell back to log2(x + 1)."))
        log2(counts + 1)
      }
    )
  } else if (method %in% c("cpm", "tmm")) {
    if (!requireNamespace("edgeR", quietly = TRUE)) {
      stop("edgeR is required for method '", method, "'.")
    }
    safe_counts <- pmax(mat, 0)
    safe_counts[is.na(safe_counts)] <- 0
    dge <- edgeR::DGEList(counts = safe_counts)
    if (identical(method, "tmm")) {
      dge <- edgeR::calcNormFactors(dge)
      factors <- dge$samples$norm.factors
    }
    norm <- edgeR::cpm(dge, log = TRUE, prior.count = 1)
  } else {
    norm <- log2(pmax(mat, 0) + 1)
  }

  if (is.null(factors)) factors <- stats::setNames(rep(1, length(ids)), ids)
  norm <- norm[rownames(mat), , drop = FALSE]

  outdir <- task$outdir
  out <- matrix_with_anno(rownames(norm), anno, norm, "gene_id")
  write_tsv_file(out, file.path(outdir, "normalized.tsv"))
  write_tsv_file(samples, file.path(outdir, "samples.tsv"))

  factors_df <- data.frame(sample_id = names(factors),
                           size_factor = as.numeric(factors),
                           stringsAsFactors = FALSE)
  write_tsv_file(factors_df, file.path(outdir, "size_factors.tsv"))

  long <- data.frame(
    sample_id = rep(ids, each = nrow(norm)),
    value = as.vector(norm),
    stringsAsFactors = FALSE
  )
  long$sample_id <- factor(long$sample_id, levels = ids)
  p <- ggplot2::ggplot(long, ggplot2::aes(x = sample_id, y = value)) +
    ggplot2::geom_boxplot(fill = "#93c5fd", outlier.size = 0.2, linewidth = 0.3) +
    ggplot2::labs(x = NULL, y = "Normalized value", title = paste("Normalized values:", method)) +
    ggplot2::theme_bw(base_size = 12) +
    ggplot2::theme(axis.text.x = ggplot2::element_text(angle = 45, hjust = 1))
  plot_art <- save_plot(p, outdir, "normalized_boxplot", width = 6, height = 4)

  list(
    ok = TRUE,
    artifacts = list(
      normalized = artifact(outdir, "normalized.tsv", "matrix", "Normalized matrix"),
      samples = artifact(outdir, "samples.tsv", "table", "Sample sheet"),
      factors = artifact(outdir, "size_factors.tsv", "table", "Size factors"),
      plot = plot_art
    ),
    metrics = list(method = method, n_genes = nrow(norm), n_samples = ncol(norm)),
    messages = notes
  )
}

rna_pca <- function(task) {
  mat <- read_tsv_file(input_path(task, "matrix"))
  samples <- read_tsv_file(input_path(task, "samples"))
  ids <- as.character(samples$sample_id)
  m <- df_to_matrix(mat, "gene_id", ids)
  group_col <- resolve_group_column(samples, task, "group")

  res <- pca_impl(
    m, samples,
    group_col = group_col,
    ntop = p_int(task, "ntop", 500),
    scale = p_bool(task, "scale", TRUE),
    label = p_bool(task, "label", TRUE),
    ellipse = p_bool(task, "ellipse", TRUE),
    title = p_str(task, "title", "PCA")
  )

  outdir <- task$outdir
  write_tsv_file(res$coords, file.path(outdir, "pca_coordinates.tsv"))
  write_tsv_file(res$variance, file.path(outdir, "pca_variance.tsv"))
  plot_art <- save_plot(res$plot, outdir, "pca", width = 6.5, height = 5)

  list(
    ok = TRUE,
    artifacts = list(
      coords = artifact(outdir, "pca_coordinates.tsv", "table", "PCA coordinates"),
      variance = artifact(outdir, "pca_variance.tsv", "table", "Variance explained"),
      plot = plot_art
    ),
    metrics = list(
      pc1 = round(res$variance$variance_explained[1] * 100, 2),
      pc2 = round(res$variance$variance_explained[2] * 100, 2),
      n_features = p_int(task, "ntop", 500)
    ),
    messages = character()
  )
}

rna_de <- function(task) {
  counts_df <- read_tsv_file(input_path(task, "counts"))
  samples <- read_tsv_file(input_path(task, "samples"))
  ids <- as.character(samples$sample_id)
  mat <- df_to_matrix(counts_df, "gene_id", ids)
  anno <- counts_df[, setdiff(names(counts_df), c("gene_id", ids)), drop = FALSE]

  group_col <- resolve_group_column(samples, task, "group")
  contrast <- pick_contrast(samples, group_col, task)
  min_count <- p_int(task, "min_count", 10)
  min_samples <- p_int(task, "min_samples", 3)

  keep <- rowSums(mat >= min_count, na.rm = TRUE) >= min_samples
  if (sum(keep) < 2) stop("Too few genes after the pre-filter.")
  counts <- round(mat[keep, , drop = FALSE])
  counts[is.na(counts)] <- 0
  if (any(counts < 0)) stop("Counts must be non-negative.")

  samples_df <- as.data.frame(samples, stringsAsFactors = FALSE)
  rownames(samples_df) <- ids
  samples_df[[group_col]] <- factor(as.character(samples_df[[group_col]]),
                                    levels = contrast$levels)

  design_formula <- p_str(task, "design_formula", "")
  design <- if (!is.null(design_formula) && nzchar(design_formula)) {
    stats::as.formula(design_formula)
  } else {
    stats::as.formula(paste0("~ `", group_col, "`"))
  }

  dds <- DESeq2::DESeqDataSetFromMatrix(
    countData = counts,
    colData = samples_df,
    design = design
  )
  dds <- DESeq2::DESeq(dds, quiet = TRUE)
  res <- DESeq2::results(
    dds,
    contrast = c(group_col, contrast$numerator, contrast$denominator)
  )

  shrink <- p_str(task, "shrink", "none")
  if (identical(shrink, "apeglm")) {
    res <- tryCatch(
      DESeq2::lfcShrink(
        dds,
        contrast = c(group_col, contrast$numerator, contrast$denominator),
        type = "apeglm",
        quiet = TRUE
      ),
      error = function(e) res
    )
  }

  tab <- as.data.frame(res)
  mat_ids <- rownames(mat)[keep]
  anno_match <- anno[match(rownames(tab), mat_ids), , drop = FALSE]
  rownames(anno_match) <- NULL
  gene_ids <- rownames(tab)
  tab <- cbind(anno_match, tab)
  if (!"gene_id" %in% names(tab)) tab$gene_id <- gene_ids
  rownames(tab) <- NULL

  padj_cutoff <- p_num(task, "padj_cutoff", 0.05)
  lfc_cutoff <- p_num(task, "lfc_cutoff", 1)
  tab$regulation <- "ns"
  if ("padj" %in% names(tab)) {
    tab$regulation[!is.na(tab$padj) & tab$padj < padj_cutoff &
                     tab$log2FoldChange >= lfc_cutoff] <- "up"
    tab$regulation[!is.na(tab$padj) & tab$padj < padj_cutoff &
                     tab$log2FoldChange <= -lfc_cutoff] <- "down"
  }

  norm_counts <- DESeq2::counts(dds, normalized = TRUE)
  for (g in levels(samples_df[[group_col]])) {
    cols <- ids[as.character(samples_df[[group_col]]) == g]
    cols <- intersect(cols, colnames(norm_counts))
    if (length(cols)) {
      tab[[paste0("mean_norm_", g)]] <- rowMeans(
        norm_counts[as.character(tab$gene_id), cols, drop = FALSE], na.rm = TRUE
      )
    }
  }

  ord <- order(tab$padj, tab$pvalue, na.last = TRUE)
  tab <- tab[ord, , drop = FALSE]
  sig <- tab[!is.na(tab$padj) & tab$padj < padj_cutoff &
               abs(tab$log2FoldChange) >= lfc_cutoff, , drop = FALSE]

  outdir <- task$outdir
  write_tsv_file(tab, file.path(outdir, "de_results.tsv"))
  write_tsv_file(sig, file.path(outdir, "de_significant.tsv"))
  write_tsv_file(
    matrix_with_anno(rownames(norm_counts), anno[keep, , drop = FALSE],
                     norm_counts, "gene_id"),
    file.path(outdir, "deseq2_norm_counts.tsv")
  )

  ma_df <- tab[!is.na(tab$baseMean) & !is.na(tab$log2FoldChange), , drop = FALSE]
  ma_df$.class <- factor(ma_df$regulation, levels = c("up", "down", "ns"))
  p <- ggplot2::ggplot(ma_df, ggplot2::aes(x = log10(baseMean + 1), y = log2FoldChange,
                                           color = .class)) +
    ggplot2::geom_point(size = 1.2, alpha = 0.7) +
    ggplot2::scale_color_manual(values = c(up = "#d97706", down = "#2563eb", ns = "grey75"),
                                drop = FALSE) +
    ggplot2::geom_hline(yintercept = 0, color = "grey45", linewidth = 0.3) +
    ggplot2::labs(x = "log10(baseMean + 1)", y = "log2 fold change",
                  color = "", title = "MA plot") +
    ggplot2::theme_bw(base_size = 12) +
    ggplot2::theme(panel.grid.minor = ggplot2::element_blank())
  plot_art <- save_plot(p, outdir, "ma_plot", width = 6, height = 4.5)

  n_up <- sum(tab$regulation == "up")
  n_down <- sum(tab$regulation == "down")
  list(
    ok = TRUE,
    artifacts = list(
      results = artifact(outdir, "de_results.tsv", "table", "DE results"),
      significant = artifact(outdir, "de_significant.tsv", "table", "Significant genes"),
      norm_counts = artifact(outdir, "deseq2_norm_counts.tsv", "matrix", "Normalized counts"),
      plot = plot_art
    ),
    metrics = list(
      contrast = paste0(contrast$numerator, " vs ", contrast$denominator),
      n_tested = nrow(tab),
      n_up = n_up,
      n_down = n_down
    ),
    messages = sprintf("%d up and %d down at FDR < %s and |log2FC| >= %s.",
                       n_up, n_down, padj_cutoff, lfc_cutoff)
  )
}

rna_volcano <- function(task) {
  df <- read_tsv_file(input_path(task, "results"))
  y_col <- if ("padj" %in% names(df) && any(!is.na(df$padj))) "padj" else "pvalue"
  label_col <- if ("gene_symbol" %in% names(df)) "gene_symbol" else "gene_id"
  res <- volcano_impl(
    df,
    x_col = "log2FoldChange",
    y_col = y_col,
    id_col = "gene_id",
    label_col = label_col,
    padj_cutoff = p_num(task, "padj_cutoff", 0.05),
    lfc_cutoff = p_num(task, "lfc_cutoff", 1),
    label_top = p_int(task, "label_top", 10),
    title = p_str(task, "title", "Volcano"),
    up_label = "Up",
    down_label = "Down"
  )

  outdir <- task$outdir
  write_tsv_file(res$summary, file.path(outdir, "volcano_summary.tsv"))
  plot_art <- save_plot(res$plot, outdir, "volcano", width = 6.5, height = 5.5)

  list(
    ok = TRUE,
    artifacts = list(
      plot = plot_art,
      summary = artifact(outdir, "volcano_summary.tsv", "table", "Count summary")
    ),
    metrics = as.list(stats::setNames(res$summary$n, res$summary$class)),
    messages = character()
  )
}

rna_heatmap <- function(task) {
  df <- read_tsv_file(input_path(task, "results"))
  mat_df <- read_tsv_file(input_path(task, "matrix"))
  samples <- read_tsv_file(input_path(task, "samples"))
  ids <- as.character(samples$sample_id)
  mat <- df_to_matrix(mat_df, "gene_id", ids)
  group_col <- resolve_group_column(samples, task, "group")

  res <- heatmap_impl(
    df, mat, samples,
    id_col = "gene_id",
    label_col = if ("gene_symbol" %in% names(df)) "gene_symbol" else "gene_id",
    top_n = p_int(task, "top_n", 50),
    group_col = group_col,
    scale_rows = p_bool(task, "scale_rows", TRUE),
    only_significant = p_bool(task, "only_significant", FALSE),
    padj_cutoff = p_num(task, "padj_cutoff", 0.05),
    lfc_cutoff = p_num(task, "lfc_cutoff", 1),
    title = p_str(task, "title", "Top DE genes"),
    feature_ids = read_feature_list(task),
    cluster_rows = p_bool(task, "cluster_rows", TRUE),
    cluster_columns = p_bool(task, "cluster_columns", TRUE),
    show_row_names = p_bool(task, "show_row_names", TRUE),
    z_cap = p_num(task, "z_cap", 2),
    color_low = p_str(task, "color_low", "#2563eb"),
    color_high = p_str(task, "color_high", "#c2410c")
  )

  outdir <- task$outdir
  write_tsv_file(res$genes, file.path(outdir, "heatmap_genes.tsv"))
  width <- p_num(task, "width", 0)
  height <- p_num(task, "height", 0)
  if (!is.finite(width) || width <= 0) width <- max(6, 0.45 * ncol(res$matrix) + 3)
  if (!is.finite(height) || height <= 0) height <- max(5, 0.18 * nrow(res$matrix) + 2.5)
  plot_art <- save_heatmap(
    res$heatmap, outdir, "heatmap",
    width = width,
    height = height
  )

  list(
    ok = TRUE,
    artifacts = list(
      plot = plot_art,
      genes = artifact(outdir, "heatmap_genes.tsv", "table", "Selected features")
    ),
    metrics = list(n_features = nrow(res$matrix), n_samples = ncol(res$matrix)),
    messages = character()
  )
}

rna_enrich_ora <- function(task) {
  df <- read_tsv_file(input_path(task, "results"))
  symbol_col <- if ("gene_symbol" %in% names(df)) "gene_symbol" else "gene_id"
  padj_col <- if ("padj" %in% names(df)) "padj" else "pvalue"
  res <- ora_impl(
    df,
    symbol_col = symbol_col,
    padj_col = padj_col,
    lfc_col = "log2FoldChange",
    organism = p_str(task, "organism", "mouse"),
    ontology = p_str(task, "ontology", "BP"),
    direction = p_str(task, "direction", "both"),
    padj_cutoff = p_num(task, "padj_cutoff", 0.05),
    lfc_cutoff = p_num(task, "lfc_cutoff", 1),
    pvalue_cutoff = p_num(task, "pvalue_cutoff", 0.05),
    qvalue_cutoff = p_num(task, "qvalue_cutoff", 0.2),
    top_n = p_int(task, "top_n", 20),
    title = "GO over-representation"
  )

  outdir <- task$outdir
  write_tsv_file(res$table, file.path(outdir, "go_ora.tsv"))
  artifacts <- list(table = artifact(outdir, "go_ora.tsv", "table", "GO enrichment table"))
  if (!is.null(res$plot)) {
    plot_height <- max(5.5, 0.2 * min(nrow(res$table), 40) + 2)
    artifacts$plot <- save_plot(res$plot, outdir, "go_ora_dotplot",
                                width = 8, height = plot_height)
  }

  list(
    ok = TRUE,
    artifacts = artifacts,
    metrics = list(n_terms = nrow(res$table)),
    messages = res$messages %||% character()
  )
}

rna_enrich_gsea <- function(task) {
  df <- read_tsv_file(input_path(task, "results"))
  symbol_col <- if ("gene_symbol" %in% names(df)) "gene_symbol" else "gene_id"
  ranking <- p_str(task, "ranking", "stat")
  rank_col <- if (identical(ranking, "log2FoldChange")) "log2FoldChange" else "stat"
  if (!rank_col %in% names(df)) rank_col <- "log2FoldChange"

  res <- gsea_impl(
    df,
    symbol_col = symbol_col,
    rank_col = rank_col,
    organism = p_str(task, "organism", "mouse"),
    ontology = p_str(task, "ontology", "BP"),
    pvalue_cutoff = p_num(task, "pvalue_cutoff", 0.05),
    min_size = p_int(task, "min_size", 10),
    max_size = p_int(task, "max_size", 500),
    top_n = p_int(task, "top_n", 20),
    seed = p_int(task, "seed", 1),
    title = "GO gene set enrichment"
  )

  outdir <- task$outdir
  write_tsv_file(res$table, file.path(outdir, "go_gsea.tsv"))
  artifacts <- list(table = artifact(outdir, "go_gsea.tsv", "table", "GSEA table"))
  if (!is.null(res$plot)) {
    plot_height <- max(5.5, 0.2 * min(nrow(res$table), 40) + 2)
    artifacts$plot <- save_plot(res$plot, outdir, "go_gsea_dotplot",
                                width = 8, height = plot_height)
  }

  list(
    ok = TRUE,
    artifacts = artifacts,
    metrics = list(n_terms = nrow(res$table)),
    messages = res$messages %||% character()
  )
}

rna_gsea_kegg <- function(task) {
  df <- read_tsv_file(input_path(task, "results"))
  mat_df <- read_tsv_file(input_path(task, "matrix"))
  samples <- read_tsv_file(input_path(task, "samples"))
  sample_ids <- as.character(samples$sample_id)
  mat <- df_to_matrix(mat_df, "gene_id", sample_ids)
  group_col <- resolve_group_column(samples, task, "group")
  ranking <- p_str(task, "ranking", "stat")
  rank_col <- if (identical(ranking, "log2FoldChange")) "log2FoldChange" else "stat"
  if (!rank_col %in% names(df)) rank_col <- "log2FoldChange"

  res <- gsea_kegg_impl(
    df, mat, samples,
    id_col = "gene_id",
    symbol_col = if ("gene_symbol" %in% names(df)) "gene_symbol" else "gene_id",
    rank_col = rank_col,
    group_col = group_col,
    organism = p_str(task, "organism", "mouse"),
    padj_cutoff = p_num(task, "padj_cutoff", 0.05),
    pvalue_cutoff = p_num(task, "pvalue_cutoff", 0.05),
    min_size = p_int(task, "min_size", 10),
    max_size = p_int(task, "max_size", 500),
    top_n = p_int(task, "top_n", 20),
    pathways = p_str(task, "pathways", ""),
    scale_method = p_str(task, "scale_method", "minmax"),
    group_labels = p_str(task, "group_labels", ""),
    color_low = p_str(task, "color_low", "#3B5998"),
    color_high = p_str(task, "color_high", "#E42528"),
    width = p_num(task, "width", 0),
    height = p_num(task, "height", 0),
    seed = p_int(task, "seed", 1)
  )

  outdir <- task$outdir
  write_tsv_file(res$table, file.path(outdir, "gsea_kegg.tsv"))
  artifacts <- list(
    table = artifact(outdir, "gsea_kegg.tsv", "table", "KEGG GSEA table")
  )
  if (!is.null(res$plot)) {
    artifacts$plot <- save_plot(res$plot, outdir, "gsea_kegg_dotplot",
                                width = 8, height = 6)
  }
  if (!is.null(res$heatmap)) {
    artifacts$heatmap <- save_heatmap_decorated(
      res$heatmap$object, outdir, "gsea_kegg_heatmap",
      width = res$heatmap$width,
      height = res$heatmap$height,
      legend_side = "bottom",
      padding = grid::unit(c(28, 12, 8, 12), "mm"),
      decorate = res$heatmap$decorate
    )
  }

  list(
    ok = TRUE,
    artifacts = artifacts,
    metrics = list(
      n_terms = nrow(res$table),
      n_significant = nrow(res$significant),
      n_genes = if (is.null(res$heatmap)) 0 else res$heatmap$n_genes
    ),
    messages = res$messages %||% character()
  )
}
