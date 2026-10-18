# prot_nodes.R -- bulk proteomics nodes for Omics Canvas.
# Inputs are MaxQuant proteinGroups.txt files or protein x sample matrices.
# All comments are English by project convention.

prot_load_maxquant <- function(task) {
  path <- p_str(task, "protein_groups")
  if (is.null(path) || !nzchar(path)) stop("Parameter 'protein_groups' is required.")
  if (!file.exists(path)) stop("proteinGroups file not found: ", path)

  pg <- read.delim(
    path,
    sep = "\t",
    header = TRUE,
    check.names = FALSE,
    stringsAsFactors = FALSE,
    quote = "",
    comment.char = "",
    na.strings = c("NA", "NaN", "")
  )
  notes <- character()

  flag_cols <- intersect(c("Reverse", "Potential contaminant", "Only identified by site"),
                         names(pg))
  for (col in flag_cols) {
    keep <- is.na(pg[[col]]) | as.character(pg[[col]]) != "+"
    pg <- pg[keep, , drop = FALSE]
  }
  pg <- pg[!is.na(pg[["Protein IDs"]]) & nzchar(as.character(pg[["Protein IDs"]])), ,
           drop = FALSE]
  if (nrow(pg) == 0) stop("No protein groups remain after removing decoys/contaminants.")

  lead <- sub(";.*", "", as.character(pg[["Protein IDs"]]))
  score <- suppressWarnings(as.numeric(pg[["Score"]]))
  score[is.na(score)] <- -Inf
  ord <- order(score, decreasing = TRUE)
  pg <- pg[ord, , drop = FALSE]
  lead <- lead[ord]
  keep <- !duplicated(lead)
  pg <- pg[keep, , drop = FALSE]
  lead <- lead[keep]
  notes <- c(notes, sprintf("%d protein groups after filtering and de-duplication.", nrow(pg)))

  intensity_type <- p_str(task, "intensity_type", "Intensity")
  prefix <- paste0(intensity_type, " ")
  value_cols <- names(pg)[startsWith(names(pg), prefix)]
  if (identical(intensity_type, "Intensity")) {
    value_cols <- value_cols[!startsWith(value_cols, "LFQ intensity ")]
  }
  sample_regex <- p_str(task, "sample_regex", "")
  if (!is.null(sample_regex) && nzchar(sample_regex)) {
    sample_names_all <- sub(paste0("^", prefix), "", value_cols)
    value_cols <- value_cols[grepl(sample_regex, sample_names_all)]
  }
  if (length(value_cols) == 0) {
    stop("No per-sample '", intensity_type, "' columns found.")
  }

  sample_names <- sub(paste0("^", prefix), "", value_cols)
  mat <- as.matrix(pg[, value_cols, drop = FALSE])
  storage.mode(mat) <- "double"
  rownames(mat) <- make.unique(lead)
  colnames(mat) <- sample_names

  sample_sheet <- p_str(task, "sample_sheet", "")
  sample_col <- p_str(task, "sample_column", "sample_id")
  group_col <- p_str(task, "group_column", "group")
  strip_regex <- p_str(task, "group_strip_regex", "[-_ ]?[0-9]+$")

  if (!is.null(sample_sheet) && nzchar(sample_sheet)) {
    if (!file.exists(sample_sheet)) stop("Sample sheet not found: ", sample_sheet)
    samples <- read_tsv_file(sample_sheet)
    if (!sample_col %in% names(samples)) {
      stop("Sample column not found in sample sheet: ", sample_col)
    }
    ids <- as.character(samples[[sample_col]])
    missing <- setdiff(ids, sample_names)
    if (length(missing)) {
      stop("Samples missing from proteinGroups: ", paste(missing, collapse = ", "))
    }
    mat <- mat[, match(ids, sample_names), drop = FALSE]
    colnames(mat) <- ids
    if (!group_col %in% names(samples)) {
      samples[[group_col]] <- infer_group(ids, strip_regex)
    }
  } else {
    ids <- sample_names
    samples <- data.frame(
      sample_id = ids,
      group = infer_group(ids, strip_regex),
      stringsAsFactors = FALSE
    )
    notes <- c(notes, "No sample sheet supplied; groups were inferred from sample names.")
  }

  features <- data.frame(
    protein_id = rownames(mat),
    protein_group = as.character(pg[["Majority protein IDs"]]),
    gene = sub(";.*", "", as.character(pg[["Gene names"]])),
    protein_name = as.character(pg[["Protein names"]]),
    mol_weight_kda = suppressWarnings(as.numeric(pg[["Mol. weight [kDa]"]])),
    peptides = suppressWarnings(as.numeric(pg[["Peptides"]])),
    unique_peptides = suppressWarnings(as.numeric(pg[["Unique peptides"]])),
    q_value = suppressWarnings(as.numeric(pg[["Q-value"]])),
    score = suppressWarnings(as.numeric(pg[["Score"]])),
    stringsAsFactors = FALSE
  )
  features$gene[is.na(features$gene)] <- ""

  samples_out <- samples
  names(samples_out)[names(samples_out) == sample_col] <- "sample_id"
  if (group_col != "group" && group_col %in% names(samples_out)) {
    names(samples_out)[names(samples_out) == group_col] <- "group"
  }
  if (!"group" %in% names(samples_out)) {
    samples_out$group <- infer_group(samples_out$sample_id, strip_regex)
  }

  outdir <- task$outdir
  mat_out <- cbind(features, as.data.frame(mat, check.names = FALSE))
  write_tsv_file(mat_out, file.path(outdir, "protein_matrix_raw.tsv"))
  write_tsv_file(samples_out, file.path(outdir, "samples.tsv"))
  write_tsv_file(features, file.path(outdir, "features.tsv"))

  long <- data.frame(
    sample_id = rep(ids, each = nrow(mat)),
    value = as.vector(mat),
    stringsAsFactors = FALSE
  )
  long <- long[is.finite(long$value) & long$value > 0, , drop = FALSE]
  long$sample_id <- factor(long$sample_id, levels = ids)
  p <- ggplot2::ggplot(long, ggplot2::aes(x = sample_id, y = log10(value + 1))) +
    ggplot2::geom_boxplot(fill = "#fdba74", outlier.size = 0.2, linewidth = 0.3) +
    ggplot2::labs(x = NULL, y = "log10(intensity + 1)", title = "Raw intensity distribution") +
    ggplot2::theme_bw(base_size = 12) +
    ggplot2::theme(axis.text.x = ggplot2::element_text(angle = 45, hjust = 1))
  plot_art <- save_plot(p, outdir, "raw_intensity_boxplot", width = 6, height = 4)

  list(
    ok = TRUE,
    artifacts = list(
      matrix = artifact(outdir, "protein_matrix_raw.tsv", "matrix", "Protein intensity matrix"),
      samples = artifact(outdir, "samples.tsv", "table", "Sample sheet"),
      features = artifact(outdir, "features.tsv", "table", "Protein annotation"),
      plot = plot_art
    ),
    metrics = list(
      n_proteins = nrow(mat),
      n_samples = ncol(mat),
      intensity_type = intensity_type
    ),
    messages = notes
  )
}

prot_filter <- function(task) {
  mat_df <- read_tsv_file(input_path(task, "matrix"))
  samples <- read_tsv_file(input_path(task, "samples"))
  ids <- as.character(samples$sample_id)
  mat <- df_to_matrix(mat_df, "protein_id", ids)
  anno <- mat_df[, setdiff(names(mat_df), c("protein_id", ids)), drop = FALSE]

  if (p_bool(task, "zero_as_missing", TRUE)) {
    mat[!is.na(mat) & mat == 0] <- NA
  }
  min_valid <- p_int(task, "min_valid", 0)
  frac <- p_num(task, "min_valid_frac", 0.5)
  threshold <- if (!is.null(min_valid) && min_valid > 0) {
    min_valid
  } else {
    max(1, ceiling(frac * ncol(mat)))
  }
  keep <- rowSums(!is.na(mat)) >= threshold

  min_peptides <- p_int(task, "min_peptides", 1)
  if (!is.null(min_peptides) && min_peptides > 1 && "unique_peptides" %in% names(anno)) {
    pep <- suppressWarnings(as.numeric(anno$unique_peptides))
    keep <- keep & (!is.na(pep) & pep >= min_peptides)
  }

  if (sum(keep) < 2) stop("Fewer than two proteins pass the filter.")
  mat_keep <- mat[keep, , drop = FALSE]
  anno_keep <- anno[keep, , drop = FALSE]

  outdir <- task$outdir
  write_tsv_file(
    matrix_with_anno(rownames(mat_keep), anno_keep, mat_keep, "protein_id"),
    file.path(outdir, "protein_matrix_filtered.tsv")
  )
  write_tsv_file(samples, file.path(outdir, "samples.tsv"))
  write_tsv_file(anno_keep, file.path(outdir, "features.tsv"))

  summary <- data.frame(
    metric = c("input_proteins", "kept_proteins", "removed_proteins",
               "required_valid_values", "min_peptides"),
    value = c(nrow(mat), nrow(mat_keep), nrow(mat) - nrow(mat_keep),
              threshold, min_peptides %||% 1)
  )
  write_tsv_file(summary, file.path(outdir, "filter_summary.tsv"))

  miss <- data.frame(
    sample_id = ids,
    pct_missing = round(100 * colMeans(is.na(mat)), 1),
    stringsAsFactors = FALSE
  )
  miss$sample_id <- factor(miss$sample_id, levels = ids)
  p <- ggplot2::ggplot(miss, ggplot2::aes(x = sample_id, y = pct_missing)) +
    ggplot2::geom_col(fill = "#c2410c", width = 0.7) +
    ggplot2::labs(x = NULL, y = "% missing", title = "Missing values per sample") +
    ggplot2::theme_bw(base_size = 12) +
    ggplot2::theme(axis.text.x = ggplot2::element_text(angle = 45, hjust = 1))
  plot_art <- save_plot(p, outdir, "missingness", width = 6, height = 4)

  list(
    ok = TRUE,
    artifacts = list(
      matrix = artifact(outdir, "protein_matrix_filtered.tsv", "matrix", "Filtered protein matrix"),
      samples = artifact(outdir, "samples.tsv", "table", "Sample sheet"),
      features = artifact(outdir, "features.tsv", "table", "Protein annotation"),
      summary = artifact(outdir, "filter_summary.tsv", "table", "Filter summary"),
      plot = plot_art
    ),
    metrics = list(
      n_input = nrow(mat),
      n_kept = nrow(mat_keep),
      pct_kept = round(100 * nrow(mat_keep) / nrow(mat), 2),
      required_valid_values = threshold
    ),
    messages = sprintf("Kept %d of %d proteins.", nrow(mat_keep), nrow(mat))
  )
}

prot_transform <- function(task) {
  mat_df <- read_tsv_file(input_path(task, "matrix"))
  samples <- read_tsv_file(input_path(task, "samples"))
  ids <- as.character(samples$sample_id)
  mat <- df_to_matrix(mat_df, "protein_id", ids)
  anno <- mat_df[, setdiff(names(mat_df), c("protein_id", ids)), drop = FALSE]
  rn <- rownames(mat)
  notes <- character()
  do_log2 <- p_bool(task, "log2", TRUE)
  pseudocount <- p_num(task, "pseudocount", 0)
  if (isTRUE(do_log2)) {
    mat[!is.na(mat) & mat <= 0] <- NA
    mat <- log2(mat + pseudocount)
  }

  method <- p_str(task, "normalize", "median")
  if (identical(method, "median")) {
    centers <- apply(mat, 2, stats::median, na.rm = TRUE)
    centers[!is.finite(centers)] <- 0
    mat <- sweep(mat, 2, centers, "-")
  } else if (identical(method, "quantile")) {
    if (anyNA(mat)) {
      notes <- c(notes, "Quantile normalization requires complete values; fell back to median normalization.")
      centers <- apply(mat, 2, stats::median, na.rm = TRUE)
      centers[!is.finite(centers)] <- 0
      mat <- sweep(mat, 2, centers, "-")
    } else {
      mat <- preprocessCore::normalize.quantiles(mat)
      rownames(mat) <- rn
      colnames(mat) <- ids
    }
  }

  outdir <- task$outdir
  write_tsv_file(
    matrix_with_anno(rownames(mat), anno, mat, "protein_id"),
    file.path(outdir, "protein_matrix_normalized.tsv")
  )
  write_tsv_file(samples, file.path(outdir, "samples.tsv"))

  long <- data.frame(
    sample_id = rep(ids, each = nrow(mat)),
    value = as.vector(mat),
    stringsAsFactors = FALSE
  )
  long <- long[is.finite(long$value), , drop = FALSE]
  long$sample_id <- factor(long$sample_id, levels = ids)
  p <- ggplot2::ggplot(long, ggplot2::aes(x = sample_id, y = value)) +
    ggplot2::geom_boxplot(fill = "#fdba74", outlier.size = 0.2, linewidth = 0.3) +
    ggplot2::labs(x = NULL, y = "Normalized log2 intensity", title = "Normalized intensities") +
    ggplot2::theme_bw(base_size = 12) +
    ggplot2::theme(axis.text.x = ggplot2::element_text(angle = 45, hjust = 1))
  plot_art <- save_plot(p, outdir, "normalized_boxplot", width = 6, height = 4)

  list(
    ok = TRUE,
    artifacts = list(
      matrix = artifact(outdir, "protein_matrix_normalized.tsv", "matrix", "Normalized matrix"),
      samples = artifact(outdir, "samples.tsv", "table", "Sample sheet"),
      plot = plot_art
    ),
    metrics = list(method = method, log2 = do_log2, n_proteins = nrow(mat)),
    messages = notes
  )
}

prot_impute <- function(task) {
  mat_df <- read_tsv_file(input_path(task, "matrix"))
  samples <- read_tsv_file(input_path(task, "samples"))
  ids <- as.character(samples$sample_id)
  mat <- df_to_matrix(mat_df, "protein_id", ids)
  anno <- mat_df[, setdiff(names(mat_df), c("protein_id", ids)), drop = FALSE]

  missing_before <- sum(is.na(mat))
  method <- p_str(task, "method", "MinProb")
  width <- p_num(task, "width", 0.3)
  downshift <- p_num(task, "downshift", 1.8)
  seed <- p_int(task, "seed", 1)
  set.seed(seed)
  notes <- character()

  if (identical(method, "MinProb") || identical(method, "MinDet")) {
    for (j in seq_len(ncol(mat))) {
      col <- mat[, j]
      missing <- is.na(col)
      if (!any(missing)) next
      observed <- col[!missing]
      if (length(observed) == 0) next
      if (identical(method, "MinProb")) {
        mu <- mean(observed) - downshift * stats::sd(observed)
        sigma <- width * stats::sd(observed)
        if (!is.finite(sigma) || sigma <= 0) sigma <- max(stats::sd(observed), 0.01)
        col[missing] <- stats::rnorm(sum(missing), mean = mu, sd = sigma)
      } else {
        col[missing] <- stats::quantile(observed, probs = 0.01, na.rm = TRUE)
      }
      mat[, j] <- col
    }
  } else if (identical(method, "kNN")) {
    if (!requireNamespace("impute", quietly = TRUE)) stop("Package impute is required for kNN.")
    k <- p_int(task, "k", 10)
    imp <- tryCatch(
      impute::impute.knn(mat, k = k, rowmax = 0.5, colmax = 0.8, maxp = 1500),
      error = function(e) NULL
    )
    if (is.null(imp)) {
      notes <- c(notes, "kNN imputation failed (too much missingness); fell back to MinProb.")
      for (j in seq_len(ncol(mat))) {
        col <- mat[, j]
        missing <- is.na(col)
        if (!any(missing)) next
        observed <- col[!missing]
        mu <- mean(observed) - downshift * stats::sd(observed)
        sigma <- max(width * stats::sd(observed), 0.01)
        col[missing] <- stats::rnorm(sum(missing), mean = mu, sd = sigma)
        mat[, j] <- col
      }
    } else {
      mat <- imp$data
    }
  } else if (!identical(method, "none")) {
    stop("Unknown imputation method: ", method)
  }

  missing_after <- sum(is.na(mat))
  outdir <- task$outdir
  write_tsv_file(
    matrix_with_anno(rownames(mat), anno, mat, "protein_id"),
    file.path(outdir, "protein_matrix_imputed.tsv")
  )
  write_tsv_file(samples, file.path(outdir, "samples.tsv"))

  summary <- data.frame(
    sample_id = ids,
    n_missing = colSums(is.na(df_to_matrix(mat_df, "protein_id", ids))),
    stringsAsFactors = FALSE
  )
  summary$n_imputed <- summary$n_missing
  summary$pct_imputed <- round(100 * summary$n_imputed / nrow(mat), 2)
  write_tsv_file(summary, file.path(outdir, "imputation_summary.tsv"))

  long <- data.frame(
    sample_id = rep(ids, each = nrow(mat)),
    value = as.vector(mat),
    stringsAsFactors = FALSE
  )
  long <- long[is.finite(long$value), , drop = FALSE]
  long$sample_id <- factor(long$sample_id, levels = ids)
  p <- ggplot2::ggplot(long, ggplot2::aes(x = value, color = sample_id)) +
    ggplot2::geom_density(linewidth = 0.5) +
    ggplot2::labs(x = "Imputed log2 intensity", y = "Density", color = NULL,
                  title = paste("Imputation:", method)) +
    ggplot2::theme_bw(base_size = 12) +
    ggplot2::theme(panel.grid.minor = ggplot2::element_blank())
  plot_art <- save_plot(p, outdir, "imputed_density", width = 6.5, height = 4.5)

  list(
    ok = TRUE,
    artifacts = list(
      matrix = artifact(outdir, "protein_matrix_imputed.tsv", "matrix", "Imputed matrix"),
      samples = artifact(outdir, "samples.tsv", "table", "Sample sheet"),
      summary = artifact(outdir, "imputation_summary.tsv", "table", "Imputation summary"),
      plot = plot_art
    ),
    metrics = list(
      method = method,
      n_missing_before = missing_before,
      n_missing_after = missing_after,
      pct_imputed = round(100 * missing_before / length(mat), 2)
    ),
    messages = notes
  )
}

prot_pca <- function(task) {
  mat_df <- read_tsv_file(input_path(task, "matrix"))
  samples <- read_tsv_file(input_path(task, "samples"))
  ids <- as.character(samples$sample_id)
  mat <- df_to_matrix(mat_df, "protein_id", ids)
  group_col <- resolve_group_column(samples, task, "group")

  res <- pca_impl(
    mat, samples,
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
      pc2 = round(res$variance$variance_explained[2] * 100, 2)
    ),
    messages = character()
  )
}

prot_de <- function(task) {
  mat_df <- read_tsv_file(input_path(task, "matrix"))
  samples <- read_tsv_file(input_path(task, "samples"))
  ids <- as.character(samples$sample_id)
  mat <- df_to_matrix(mat_df, "protein_id", ids)
  anno <- mat_df[, setdiff(names(mat_df), c("protein_id", ids)), drop = FALSE]

  if (anyNA(mat)) {
    stop("The protein matrix still contains missing values; run the impute node first.")
  }
  group_col <- resolve_group_column(samples, task, "group")
  contrast <- pick_contrast(samples, group_col, task)

  grp <- factor(as.character(samples[[group_col]]), levels = contrast$levels)
  design <- stats::model.matrix(~0 + grp)
  colnames(design) <- make.names(sub("^grp", "", colnames(design)))
  num_safe <- make.names(contrast$numerator)
  den_safe <- make.names(contrast$denominator)
  cm <- limma::makeContrasts(
    contrasts = paste0(num_safe, "-", den_safe),
    levels = design
  )

  fit <- limma::lmFit(mat, design)
  fit2 <- limma::contrasts.fit(fit, cm)
  fit2 <- limma::eBayes(
    fit2,
    trend = p_bool(task, "trend", TRUE),
    robust = p_bool(task, "robust", TRUE)
  )
  adjust <- p_str(task, "adjust", "BH")
  if (identical(adjust, "none")) adjust <- "none"
  tt <- limma::topTable(fit2, number = Inf, sort.by = "P", adjust.method = adjust)
  tt$protein_id <- rownames(tt)
  anno_match <- anno[match(tt$protein_id, rownames(mat)), , drop = FALSE]
  rownames(anno_match) <- NULL
  tt <- cbind(anno_match, tt)
  rownames(tt) <- NULL

  padj_cutoff <- p_num(task, "padj_cutoff", 0.05)
  lfc_cutoff <- p_num(task, "lfc_cutoff", 1)
  padj_col <- if ("adj.P.Val" %in% names(tt)) "adj.P.Val" else "P.Value"
  tt$regulation <- "ns"
  tt$regulation[!is.na(tt[[padj_col]]) & tt[[padj_col]] < padj_cutoff &
                  tt$logFC >= lfc_cutoff] <- "up"
  tt$regulation[!is.na(tt[[padj_col]]) & tt[[padj_col]] < padj_cutoff &
                  tt$logFC <= -lfc_cutoff] <- "down"

  for (g in contrast$levels) {
    cols <- ids[as.character(samples[[group_col]]) == g]
    if (length(cols)) {
      tt[[paste0("mean_", g)]] <- rowMeans(mat[tt$protein_id, cols, drop = FALSE],
                                            na.rm = TRUE)
    }
  }

  ord <- order(tt[[padj_col]], tt$P.Value, na.last = TRUE)
  tt <- tt[ord, , drop = FALSE]
  sig <- tt[!is.na(tt[[padj_col]]) & tt[[padj_col]] < padj_cutoff &
              abs(tt$logFC) >= lfc_cutoff, , drop = FALSE]

  outdir <- task$outdir
  write_tsv_file(tt, file.path(outdir, "prot_de_results.tsv"))
  write_tsv_file(sig, file.path(outdir, "prot_de_significant.tsv"))

  p <- ggplot2::ggplot(tt, ggplot2::aes(x = AveExpr, y = logFC, color = regulation)) +
    ggplot2::geom_point(size = 1.4, alpha = 0.75) +
    ggplot2::scale_color_manual(values = c(up = "#d97706", down = "#2563eb", ns = "grey75"),
                                drop = FALSE) +
    ggplot2::geom_hline(yintercept = 0, color = "grey45", linewidth = 0.3) +
    ggplot2::labs(x = "Average log2 intensity", y = "log2 fold change",
                  color = "", title = "MA plot") +
    ggplot2::theme_bw(base_size = 12) +
    ggplot2::theme(panel.grid.minor = ggplot2::element_blank())
  plot_art <- save_plot(p, outdir, "ma_plot", width = 6, height = 4.5)

  list(
    ok = TRUE,
    artifacts = list(
      results = artifact(outdir, "prot_de_results.tsv", "table", "DE results"),
      significant = artifact(outdir, "prot_de_significant.tsv", "table", "Significant proteins"),
      plot = plot_art
    ),
    metrics = list(
      contrast = paste0(contrast$numerator, " vs ", contrast$denominator),
      n_tested = nrow(tt),
      n_up = sum(tt$regulation == "up"),
      n_down = sum(tt$regulation == "down")
    ),
    messages = sprintf("%d up and %d down at FDR < %s and |log2FC| >= %s.",
                       sum(tt$regulation == "up"), sum(tt$regulation == "down"),
                       padj_cutoff, lfc_cutoff)
  )
}

prot_volcano <- function(task) {
  df <- read_tsv_file(input_path(task, "results"))
  y_col <- if ("adj.P.Val" %in% names(df) && any(!is.na(df[["adj.P.Val"]]))) {
    "adj.P.Val"
  } else {
    "P.Value"
  }
  label_col <- if ("gene" %in% names(df)) "gene" else "protein_id"
  res <- volcano_impl(
    df,
    x_col = "logFC",
    y_col = y_col,
    id_col = "protein_id",
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

prot_heatmap <- function(task) {
  df <- read_tsv_file(input_path(task, "results"))
  mat_df <- read_tsv_file(input_path(task, "matrix"))
  samples <- read_tsv_file(input_path(task, "samples"))
  ids <- as.character(samples$sample_id)
  mat <- df_to_matrix(mat_df, "protein_id", ids)
  group_col <- resolve_group_column(samples, task, "group")

  res <- heatmap_impl(
    df, mat, samples,
    id_col = "protein_id",
    label_col = if ("gene" %in% names(df)) "gene" else "protein_id",
    top_n = p_int(task, "top_n", 50),
    group_col = group_col,
    scale_rows = p_bool(task, "scale_rows", TRUE),
    only_significant = p_bool(task, "only_significant", FALSE),
    padj_cutoff = p_num(task, "padj_cutoff", 0.05),
    lfc_cutoff = p_num(task, "lfc_cutoff", 1),
    title = p_str(task, "title", "Top DE proteins"),
    feature_ids = read_feature_list(task),
    cluster_rows = p_bool(task, "cluster_rows", TRUE),
    cluster_columns = p_bool(task, "cluster_columns", TRUE),
    show_row_names = p_bool(task, "show_row_names", TRUE),
    z_cap = p_num(task, "z_cap", 2),
    color_low = p_str(task, "color_low", "#2563eb"),
    color_high = p_str(task, "color_high", "#c2410c")
  )

  outdir <- task$outdir
  write_tsv_file(res$genes, file.path(outdir, "heatmap_proteins.tsv"))
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
      genes = artifact(outdir, "heatmap_proteins.tsv", "table", "Selected proteins")
    ),
    metrics = list(n_features = nrow(res$matrix), n_samples = ncol(res$matrix)),
    messages = character()
  )
}

prot_enrich_ora <- function(task) {
  df <- read_tsv_file(input_path(task, "results"))
  symbol_col <- if ("gene" %in% names(df)) "gene" else "protein_id"
  padj_col <- if ("adj.P.Val" %in% names(df)) "adj.P.Val" else "P.Value"
  res <- ora_impl(
    df,
    symbol_col = symbol_col,
    padj_col = padj_col,
    lfc_col = "logFC",
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
