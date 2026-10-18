# common.R -- shared helpers for the Omics Canvas R nodes.
# All comments are English by project convention.

suppressPackageStartupMessages({
  library(jsonlite)
})

`%||%` <- function(a, b) {
  if (is.null(a)) return(b)
  if (length(a) == 0) return(b)
  if (length(a) == 1 && is.na(a)) return(b)
  a
}

p_raw <- function(task, name, default = NULL) {
  v <- task$params[[name]]
  if (is.null(v)) default else v
}

p_str <- function(task, name, default = NULL) {
  v <- p_raw(task, name, default)
  if (is.null(v)) return(NULL)
  v <- as.character(v)
  if (length(v) == 0) return(NULL)
  v[1]
}

p_num <- function(task, name, default = NULL) {
  v <- p_raw(task, name, default)
  if (is.null(v)) return(NULL)
  as.numeric(v)[1]
}

p_int <- function(task, name, default = NULL) {
  v <- p_raw(task, name, default)
  if (is.null(v)) return(NULL)
  as.integer(v)[1]
}

p_bool <- function(task, name, default = FALSE) {
  v <- p_raw(task, name, default)
  if (is.null(v)) return(default)
  isTRUE(as.logical(v)[1])
}

input_path <- function(task, port) {
  p <- task$inputs[[port]]
  if (is.null(p) || !nzchar(p)) stop("Missing required input port: ", port)
  if (!file.exists(p)) stop("Input artifact not found: ", p)
  p
}

has_input <- function(task, port) {
  p <- task$inputs[[port]]
  !is.null(p) && length(p) == 1 && nzchar(p)
}

read_tsv_file <- function(path) {
  if (!file.exists(path)) stop("Input file not found: ", path)
  read.delim(
    path,
    sep = "\t",
    header = TRUE,
    check.names = FALSE,
    stringsAsFactors = FALSE,
    na.strings = c("NA", "NaN", "")
  )
}

write_tsv_file <- function(df, path) {
  write.table(
    df,
    file = path,
    sep = "\t",
    quote = FALSE,
    row.names = FALSE,
    na = "NA"
  )
}

artifact <- function(outdir, file, type = "file", label = NULL) {
  full <- file.path(outdir, file)
  list(
    file = file,
    type = type,
    label = label %||% file,
    size_bytes = unname(file.info(full)$size)
  )
}

ensure_dir <- function(path) {
  dir.create(path, recursive = TRUE, showWarnings = FALSE)
  path
}

save_plot <- function(plot, outdir, name, width = 7, height = 5, dpi = 150) {
  png_path <- file.path(outdir, paste0(name, ".png"))
  pdf_path <- file.path(outdir, paste0(name, ".pdf"))
  ggplot2::ggsave(png_path, plot = plot, width = width, height = height, dpi = dpi)
  ggplot2::ggsave(pdf_path, plot = plot, width = width, height = height)
  artifact(outdir, basename(png_path), "plot", name)
}

save_heatmap_decorated <- function(ht, outdir, name, width = 8, height = 8,
                                    dpi = 150, legend_side = "bottom",
                                    padding = grid::unit(c(2, 2, 2, 2), "mm"),
                                    decorate = NULL) {
  png_path <- file.path(outdir, paste0(name, ".png"))
  pdf_path <- file.path(outdir, paste0(name, ".pdf"))
  grDevices::png(png_path, width = width, height = height, units = "in", res = dpi)
  ComplexHeatmap::draw(ht, heatmap_legend_side = legend_side, padding = padding)
  if (is.function(decorate)) decorate()
  grDevices::dev.off()
  grDevices::pdf(pdf_path, width = width, height = height)
  ComplexHeatmap::draw(ht, heatmap_legend_side = legend_side, padding = padding)
  if (is.function(decorate)) decorate()
  grDevices::dev.off()
  artifact(outdir, basename(png_path), "plot", name)
}

calc_gsea_curve <- function(hits_idx, n_total, weights) {
  if (!length(hits_idx) || length(hits_idx) >= n_total) return(rep(0, n_total))
  is_hit <- rep(0, n_total)
  is_hit[hits_idx] <- 1
  p_hit <- cumsum((is_hit * abs(weights)) / sum(is_hit * abs(weights)))
  p_miss <- cumsum((1 - is_hit) / (n_total - length(hits_idx)))
  es <- p_hit - p_miss
  es / max(abs(es))
}

save_heatmap <- function(ht, outdir, name, width = 8, height = 8, dpi = 150,
                         legend_side = "right",
                         padding = grid::unit(c(2, 2, 2, 2), "mm")) {
  png_path <- file.path(outdir, paste0(name, ".png"))
  pdf_path <- file.path(outdir, paste0(name, ".pdf"))
  grDevices::png(png_path, width = width, height = height, units = "in", res = dpi)
  ComplexHeatmap::draw(ht, heatmap_legend_side = legend_side, padding = padding)
  grDevices::dev.off()
  grDevices::pdf(pdf_path, width = width, height = height)
  ComplexHeatmap::draw(ht, heatmap_legend_side = legend_side, padding = padding)
  grDevices::dev.off()
  artifact(outdir, basename(png_path), "plot", name)
}

numeric_columns <- function(df, exclude = character()) {
  cols <- setdiff(names(df), exclude)
  cols[vapply(df[cols], is.numeric, logical(1))]
}

df_to_matrix <- function(df, id_col, sample_cols = NULL) {
  if (!id_col %in% names(df)) stop("ID column not found: ", id_col)
  if (is.null(sample_cols)) {
    sample_cols <- numeric_columns(df, exclude = id_col)
  }
  missing_cols <- setdiff(sample_cols, names(df))
  if (length(missing_cols)) {
    stop("Sample columns missing from table: ", paste(missing_cols, collapse = ", "))
  }
  m <- as.matrix(df[, sample_cols, drop = FALSE])
  storage.mode(m) <- "double"
  rownames(m) <- make.unique(as.character(df[[id_col]]))
  m
}

matrix_to_df <- function(mat, id_col = "gene_id", id_values = rownames(mat), anno = NULL) {
  out <- data.frame(
    id = as.character(id_values),
    mat,
    check.names = FALSE,
    stringsAsFactors = FALSE
  )
  names(out)[1] <- id_col
  if (!is.null(anno)) {
    anno <- as.data.frame(anno, stringsAsFactors = FALSE)
    keep <- setdiff(names(out), names(anno))
    out <- cbind(anno, out[, keep, drop = FALSE])
  }
  out
}

matrix_with_anno <- function(ids, anno, mat, id_col = "gene_id") {
  out <- data.frame(id = as.character(ids), stringsAsFactors = FALSE)
  names(out)[1] <- id_col
  if (!is.null(anno) && ncol(anno) > 0) {
    anno <- as.data.frame(anno, stringsAsFactors = FALSE)
    rownames(anno) <- NULL
    out <- cbind(out, anno)
  }
  cbind(out, as.data.frame(mat, check.names = FALSE))
}

align_samples <- function(mat, samples, sample_col = "sample_id") {
  if (!sample_col %in% names(samples)) {
    stop("Sample column not found: ", sample_col)
  }
  ids <- as.character(samples[[sample_col]])
  dup <- duplicated(ids)
  if (any(dup)) stop("Duplicated sample IDs in sample sheet: ", paste(ids[dup], collapse = ", "))
  missing <- setdiff(ids, colnames(mat))
  if (length(missing)) {
    stop("Samples not present in the matrix: ", paste(missing, collapse = ", "))
  }
  mat[, ids, drop = FALSE]
}

infer_group <- function(x, strip = "[-_ ]?[0-9]+$") {
  out <- sub(strip, "", as.character(x))
  out[!nzchar(out)] <- as.character(x)[!nzchar(out)]
  out
}

resolve_group_column <- function(samples, task, default = "group") {
  col <- p_str(task, "group_column", default)
  if (!is.null(col) && nzchar(col) && col %in% names(samples)) return(col)
  if ("group" %in% names(samples)) return("group")
  stop("Group column not found in sample sheet; expected a 'group' column.")
}

pick_contrast <- function(samples, group_col, task) {
  values <- as.character(samples[[group_col]])
  levs <- unique(values[!is.na(values)])
  if (length(levs) < 2) stop("At least two groups are required for differential analysis.")
  num <- p_str(task, "numerator", "")
  den <- p_str(task, "denominator", "")
  if (is.null(num) || !nzchar(num)) num <- levs[length(levs)]
  if (is.null(den) || !nzchar(den)) den <- levs[1]
  if (!num %in% levs) stop("Numerator level not found: ", num)
  if (!den %in% levs) stop("Denominator level not found: ", den)
  if (identical(num, den)) stop("Numerator and denominator must differ.")
  list(numerator = num, denominator = den, levels = levs)
}

select_top_variable <- function(mat, ntop = 500) {
  vars <- apply(mat, 1, stats::var, na.rm = TRUE)
  vars[!is.finite(vars)] <- 0
  ord <- order(vars, decreasing = TRUE)
  ord <- ord[vars[ord] > 0]
  ord[seq_len(min(ntop, length(ord)))]
}

pca_impl <- function(mat, samples, group_col, ntop = 500, scale = TRUE,
                     label = TRUE, ellipse = TRUE, title = "PCA") {
  mat <- align_samples(mat, samples)
  keep <- complete.cases(mat)
  mat <- mat[keep, , drop = FALSE]
  if (nrow(mat) < 3) stop("Too few complete features for PCA.")
  idx <- select_top_variable(mat, ntop)
  if (length(idx) < 2) stop("Not enough variable features for PCA.")
  pca <- stats::prcomp(t(mat[idx, , drop = FALSE]), center = TRUE, scale. = scale)
  ve <- (pca$sdev^2) / sum(pca$sdev^2)
  n_pc <- min(4, ncol(pca$x))
  coords <- as.data.frame(pca$x[, seq_len(n_pc), drop = FALSE])
  coords$sample_id <- rownames(coords)
  coords <- coords[, c("sample_id", paste0("PC", seq_len(n_pc)))]

  samples <- as.data.frame(samples, stringsAsFactors = FALSE)
  merged <- merge(samples, coords, by = "sample_id", sort = FALSE)
  merged <- merged[match(as.character(samples$sample_id), merged$sample_id), , drop = FALSE]
  merged[[group_col]] <- factor(as.character(merged[[group_col]]))

  variance <- data.frame(
    component = paste0("PC", seq_along(ve)),
    variance_explained = ve,
    cumulative = cumsum(ve)
  )

  x_lab <- sprintf("PC1 (%.1f%%)", ve[1] * 100)
  y_lab <- sprintf("PC2 (%.1f%%)", ve[2] * 100)
  p <- ggplot2::ggplot(
    merged,
    ggplot2::aes(x = PC1, y = PC2, color = .data[[group_col]])
  ) +
    ggplot2::geom_point(size = 3, alpha = 0.9) +
    ggplot2::labs(x = x_lab, y = y_lab, color = group_col, title = title) +
    ggplot2::theme_bw(base_size = 12) +
    ggplot2::theme(panel.grid.minor = ggplot2::element_blank())

  if (isTRUE(label) && "sample_id" %in% names(merged)) {
    p <- p + ggrepel::geom_text_repel(
      ggplot2::aes(label = sample_id),
      size = 3,
      max.overlaps = 30,
      show.legend = FALSE
    )
  }
  if (isTRUE(ellipse)) {
    counts <- table(merged[[group_col]])
    if (length(counts) >= 1 && all(counts >= 3)) {
      p <- p + ggplot2::stat_ellipse(level = 0.95, linewidth = 0.4, show.legend = FALSE)
    }
  }

  list(coords = merged, variance = variance, plot = p)
}

volcano_impl <- function(df, x_col, y_col, id_col, label_col,
                         padj_cutoff = 0.05, lfc_cutoff = 1,
                         label_top = 10, title = "Volcano",
                         up_label = "Up", down_label = "Down") {
  if (!x_col %in% names(df)) stop("Fold-change column not found: ", x_col)
  if (!y_col %in% names(df)) stop("P-value column not found: ", y_col)
  df <- as.data.frame(df, stringsAsFactors = FALSE)
  df$.x <- suppressWarnings(as.numeric(df[[x_col]]))
  df$.y <- suppressWarnings(as.numeric(df[[y_col]]))
  df <- df[!is.na(df$.x) & !is.na(df$.y), , drop = FALSE]
  if (nrow(df) == 0) stop("No rows with both fold change and p-value.")
  df$.y[df$.y <= 0] <- .Machine$double.xmin
  df$.neglog <- -log10(df$.y)

  df$.class <- "NS"
  df$.class[df$.y < padj_cutoff & df$.x >= lfc_cutoff] <- "Up"
  df$.class[df$.y < padj_cutoff & df$.x <= -lfc_cutoff] <- "Down"
  df$.class <- factor(df$.class, levels = c("Up", "Down", "NS"))

  n_up <- sum(df$.class == "Up")
  n_down <- sum(df$.class == "Down")
  n_ns <- sum(df$.class == "NS")

  cols <- c("Up" = "#d97706", "Down" = "#2563eb", "NS" = "grey75")
  p <- ggplot2::ggplot(df, ggplot2::aes(x = .x, y = .neglog, color = .class)) +
    ggplot2::geom_point(size = 1.6, alpha = 0.8) +
    ggplot2::scale_color_manual(values = cols, drop = FALSE) +
    ggplot2::geom_vline(xintercept = c(-lfc_cutoff, lfc_cutoff),
                        linetype = "dashed", color = "grey55", linewidth = 0.3) +
    ggplot2::geom_hline(yintercept = -log10(padj_cutoff),
                        linetype = "dashed", color = "grey55", linewidth = 0.3) +
    ggplot2::labs(
      x = x_col,
      y = paste0("-log10(", y_col, ")"),
      color = "",
      title = title,
      subtitle = sprintf("%s: %d   %s: %d   NS: %d", up_label, n_up, down_label, n_down, n_ns)
    ) +
    ggplot2::theme_bw(base_size = 12) +
    ggplot2::theme(panel.grid.minor = ggplot2::element_blank())

  if (isTRUE(label_top > 0) && n_up + n_down > 0) {
    sig <- df[df$.class != "NS", , drop = FALSE]
    sig <- sig[order(sig$.y, -abs(sig$.x)), , drop = FALSE]
    sig <- sig[seq_len(min(label_top, nrow(sig))), , drop = FALSE]
    if (label_col %in% names(sig)) {
      sig$.label <- as.character(sig[[label_col]])
      sig$.label[is.na(sig$.label) | !nzchar(sig$.label)] <- as.character(sig[[id_col]])[
        is.na(sig$.label) | !nzchar(sig$.label)
      ]
      p <- p + ggrepel::geom_text_repel(
        data = sig,
        ggplot2::aes(label = .label),
        size = 3,
        max.overlaps = 20,
        show.legend = FALSE
      )
    }
  }

  summary <- data.frame(
    class = c("Up", "Down", "NS", "Total"),
    n = c(n_up, n_down, n_ns, nrow(df))
  )
  list(plot = p, summary = summary, table = df)
}

zscore_rows <- function(mat, cap = 2) {
  centered <- mat - rowMeans(mat, na.rm = TRUE)
  sds <- apply(mat, 1, stats::sd, na.rm = TRUE)
  sds[!is.finite(sds) | sds == 0] <- 1
  z <- centered / sds
  z[!is.finite(z)] <- 0
  z[z > cap] <- cap
  z[z < -cap] <- -cap
  z
}

read_feature_list <- function(task) {
  path <- p_str(task, "feature_list", "")
  if (!nzchar(path)) return(NULL)
  if (!grepl("^(/|[A-Za-z]:[\\/])", path)) path <- file.path(task$workdir, path)
  if (!file.exists(path)) stop("Feature list file not found: ", path)
  ids <- trimws(readLines(path, warn = FALSE))
  ids[nzchar(ids)]
}

heatmap_impl <- function(df, mat, samples, id_col, label_col,
                         top_n = 50, group_col = "group", scale_rows = TRUE,
                         only_significant = FALSE, padj_cutoff = 0.05,
                         lfc_cutoff = 1, title = "Top features",
                         feature_ids = NULL, cluster_rows = TRUE,
                         cluster_columns = TRUE, show_row_names = TRUE,
                         z_cap = 2, color_low = "#2563eb",
                         color_high = "#c2410c") {
  df <- as.data.frame(df, stringsAsFactors = FALSE)
  if (!id_col %in% names(df)) stop("ID column not found: ", id_col)
  df$.padj <- if ("padj" %in% names(df)) as.numeric(df$padj) else
    if ("adj.P.Val" %in% names(df)) as.numeric(df[["adj.P.Val"]]) else NA_real_
  df$.lfc <- if ("log2FoldChange" %in% names(df)) as.numeric(df$log2FoldChange) else
    if ("logFC" %in% names(df)) as.numeric(df$logFC) else NA_real_

  if (isTRUE(only_significant)) {
    df <- df[!is.na(df$.padj) & df$.padj < padj_cutoff &
               abs(df$.lfc) >= lfc_cutoff, , drop = FALSE]
  }
  if (nrow(df) == 0) stop("No features selected for the heatmap.")
  if (length(feature_ids)) {
    keep <- as.character(df[[id_col]]) %in% feature_ids
    if (label_col %in% names(df)) {
      keep <- keep | as.character(df[[label_col]]) %in% feature_ids
    }
    df <- df[keep, , drop = FALSE]
    if (nrow(df) == 0) stop("None of the requested features were found.")
    rank <- match(as.character(df[[id_col]]), feature_ids)
    if (label_col %in% names(df)) {
      rank <- pmin(rank, match(as.character(df[[label_col]]), feature_ids), na.rm = TRUE)
    }
    rank[is.na(rank)] <- length(feature_ids) + seq_len(sum(is.na(rank)))
    df <- df[order(rank), , drop = FALSE]
  } else {
    ord <- order(df$.padj, -abs(df$.lfc), na.last = TRUE)
    df <- df[ord, , drop = FALSE]
  }
  df <- df[!duplicated(df[[id_col]]), , drop = FALSE]
  limit <- if (length(feature_ids)) nrow(df) else top_n
  df <- df[seq_len(min(limit, nrow(df))), , drop = FALSE]

  mat <- align_samples(mat, samples)
  ids <- intersect(as.character(df[[id_col]]), rownames(mat))
  if (length(ids) < 2) stop("Fewer than two selected features are present in the matrix.")
  df <- df[match(ids, as.character(df[[id_col]])), , drop = FALSE]
  m <- mat[ids, , drop = FALSE]

  if (isTRUE(scale_rows)) {
    m <- zscore_rows(m)
    heat_name <- "z-score"
  } else {
    heat_name <- "value"
  }
  cap <- suppressWarnings(as.numeric(z_cap))
  if (!is.finite(cap) || cap <= 0) cap <- 2
  if (isTRUE(scale_rows)) m[m > cap] <- cap
  if (isTRUE(scale_rows)) m[m < -cap] <- -cap

  labels <- if (label_col %in% names(df)) as.character(df[[label_col]]) else ids
  labels[is.na(labels) | !nzchar(labels)] <- ids[is.na(labels) | !nzchar(labels)]
  rownames(m) <- make.unique(labels)

  sample_meta <- as.data.frame(samples, stringsAsFactors = FALSE)
  sample_meta <- sample_meta[match(colnames(m), as.character(sample_meta$sample_id)), , drop = FALSE]
  groups <- factor(as.character(sample_meta[[group_col]]))
  palette <- c("#2563eb", "#c2410c", "#059669", "#7c3aed", "#be123c", "#0891b2", "#a16207")
  group_cols <- stats::setNames(palette[seq_along(levels(groups))], levels(groups))
  top_anno <- ComplexHeatmap::HeatmapAnnotation(
    group = groups,
    col = list(group = group_cols),
    annotation_name_side = "left"
  )

  lim <- max(abs(m), na.rm = TRUE)
  if (!is.finite(lim) || lim == 0) lim <- 1
  if (isTRUE(scale_rows)) lim <- cap
  col_fun <- circlize::colorRamp2(c(-lim, 0, lim), c(color_low, "white", color_high))

  ht <- ComplexHeatmap::Heatmap(
    m,
    name = heat_name,
    col = col_fun,
    top_annotation = top_anno,
    column_split = groups,
    cluster_column_slices = FALSE,
    cluster_rows = isTRUE(cluster_rows),
    cluster_columns = isTRUE(cluster_columns),
    show_row_names = isTRUE(show_row_names),
    show_column_names = TRUE,
    row_names_gp = grid::gpar(fontsize = 7),
    column_names_gp = grid::gpar(fontsize = 8),
    column_title = title,
    row_title = sprintf("%d features", nrow(m)),
    border = TRUE
  )

  genes <- data.frame(
    id = ids,
    label = labels,
    padj = df$.padj,
    log2FC = df$.lfc,
    stringsAsFactors = FALSE
  )
  list(heatmap = ht, genes = genes, matrix = m)
}

orgdb_for <- function(organism) {
  organism <- tolower(organism %||% "mouse")
  if (organism %in% c("mouse", "mm", "mmusculus", "mus musculus")) {
    if (!requireNamespace("org.Mm.eg.db", quietly = TRUE)) {
      stop("Package org.Mm.eg.db is required for mouse enrichment.")
    }
    return(org.Mm.eg.db::org.Mm.eg.db)
  }
  if (organism %in% c("human", "hs", "hsapiens", "homo sapiens")) {
    if (!requireNamespace("org.Hs.eg.db", quietly = TRUE)) {
      stop("Package org.Hs.eg.db is required for human enrichment.")
    }
    return(org.Hs.eg.db::org.Hs.eg.db)
  }
  stop("Unsupported organism: ", organism)
}

map_symbols_to_entrez <- function(symbols, orgdb) {
  symbols <- unique(as.character(symbols))
  symbols <- symbols[!is.na(symbols) & nzchar(symbols)]
  if (length(symbols) == 0) {
    return(data.frame(SYMBOL = character(), ENTREZID = character()))
  }
  mapped <- suppressMessages(AnnotationDbi::select(
    orgdb,
    keys = symbols,
    keytype = "SYMBOL",
    columns = "ENTREZID"
  ))
  mapped <- mapped[!is.na(mapped$ENTREZID), , drop = FALSE]
  mapped[!duplicated(mapped$SYMBOL), , drop = FALSE]
}

empty_enrich_table <- function() {
  data.frame(
    direction = character(),
    ID = character(),
    Description = character(),
    GeneRatio = character(),
    BgRatio = character(),
    pvalue = numeric(),
    p.adjust = numeric(),
    qvalue = numeric(),
    geneID = character(),
    Count = integer(),
    stringsAsFactors = FALSE
  )
}

empty_gsea_table <- function() {
  data.frame(
    ID = character(),
    Description = character(),
    setSize = integer(),
    enrichmentScore = numeric(),
    NES = numeric(),
    pvalue = numeric(),
    p.adjust = numeric(),
    qvalue = numeric(),
    rank = integer(),
    leading_edge = character(),
    core_enrichment = character(),
    ONTOLOGY = character(),
    stringsAsFactors = FALSE
  )
}

ratio_to_numeric <- function(x) {
  vapply(
    strsplit(as.character(x), "/", fixed = TRUE),
    function(z) if (length(z) == 2) as.numeric(z[1]) / as.numeric(z[2]) else NA_real_,
    numeric(1)
  )
}

enrich_dotplot <- function(tab, top_n = 20, title = "GO enrichment",
                           by_direction = FALSE) {
  tab <- as.data.frame(tab, stringsAsFactors = FALSE)
  tab$p.adjust <- suppressWarnings(as.numeric(tab$p.adjust))
  tab <- tab[!is.na(tab$p.adjust), , drop = FALSE]
  if (nrow(tab) == 0) return(NULL)
  tab <- tab[order(tab$p.adjust), , drop = FALSE]
  if (isTRUE(by_direction) && "direction" %in% names(tab)) {
    # Keep the strongest terms from each direction so one side cannot crowd
    # the other out of the figure.
    tab <- do.call(
      rbind,
      lapply(split(tab, tab$direction), function(part) {
        part <- part[order(part$p.adjust), , drop = FALSE]
        part[seq_len(min(top_n, nrow(part))), , drop = FALSE]
      })
    )
    rownames(tab) <- NULL
  } else {
    tab <- tab[seq_len(min(top_n, nrow(tab))), , drop = FALSE]
  }
  tab$Description <- factor(tab$Description, levels = rev(unique(tab$Description)))
  tab$.ratio <- ratio_to_numeric(tab$GeneRatio)
  tab$Count <- suppressWarnings(as.numeric(tab$Count))
  p <- ggplot2::ggplot(tab, ggplot2::aes(x = .ratio, y = Description)) +
    ggplot2::geom_point(ggplot2::aes(size = Count, color = p.adjust)) +
    ggplot2::scale_color_viridis_c(trans = "log10", option = "C", direction = -1) +
    ggplot2::scale_size_continuous(range = c(1.5, 5)) +
    ggplot2::labs(
      x = "Gene ratio",
      y = NULL,
      color = "p.adjust",
      size = "Count",
      title = title
    ) +
    ggplot2::theme_bw(base_size = 11) +
    ggplot2::theme(panel.grid.minor = ggplot2::element_blank())
  if (isTRUE(by_direction) && "direction" %in% names(tab)) {
    p <- p + ggplot2::facet_wrap(~direction, scales = "free_y", ncol = 1)
  }
  p
}

gsea_dotplot <- function(tab, top_n = 20, title = "GO gene set enrichment") {
  tab <- as.data.frame(tab, stringsAsFactors = FALSE)
  tab$p.adjust <- suppressWarnings(as.numeric(tab$p.adjust))
  tab$p.adjust[!is.na(tab$p.adjust) & tab$p.adjust <= 0] <- .Machine$double.xmin
  tab$NES <- suppressWarnings(as.numeric(tab$NES))
  tab$setSize <- suppressWarnings(as.numeric(tab$setSize))
  tab <- tab[!is.na(tab$p.adjust) & is.finite(tab$NES), , drop = FALSE]
  if (nrow(tab) == 0) return(NULL)
  tab <- tab[order(tab$p.adjust), , drop = FALSE]
  tab <- tab[seq_len(min(top_n, nrow(tab))), , drop = FALSE]
  tab$Description <- factor(tab$Description, levels = rev(unique(tab$Description)))
  p <- ggplot2::ggplot(tab, ggplot2::aes(x = NES, y = Description)) +
    ggplot2::geom_point(ggplot2::aes(size = setSize, color = p.adjust)) +
    ggplot2::scale_color_viridis_c(trans = "log10", option = "C", direction = -1) +
    ggplot2::scale_size_continuous(range = c(1.5, 5)) +
    ggplot2::geom_vline(xintercept = 0, linetype = "dashed", color = "grey55",
                        linewidth = 0.3) +
    ggplot2::labs(
      x = "Normalized enrichment score (NES)",
      y = NULL,
      color = "p.adjust",
      size = "Set size",
      title = title
    ) +
    ggplot2::theme_bw(base_size = 11) +
    ggplot2::theme(panel.grid.minor = ggplot2::element_blank())
  if ("ONTOLOGY" %in% names(tab) && length(unique(tab$ONTOLOGY)) > 1) {
    p <- p + ggplot2::facet_wrap(~ONTOLOGY, scales = "free_y", ncol = 1)
  }
  p
}

ora_impl <- function(df, symbol_col, padj_col, lfc_col, organism = "mouse",
                     ontology = "BP", direction = "both", padj_cutoff = 0.05,
                     lfc_cutoff = 1, pvalue_cutoff = 0.05, qvalue_cutoff = 0.2,
                     top_n = 20, title = "GO over-representation") {
  df <- as.data.frame(df, stringsAsFactors = FALSE)
  if (!symbol_col %in% names(df)) stop("Gene symbol column not found: ", symbol_col)
  df$.padj <- suppressWarnings(as.numeric(df[[padj_col]]))
  df$.lfc <- suppressWarnings(as.numeric(df[[lfc_col]]))

  directions <- if (identical(direction, "both")) c("up", "down") else direction
  results <- list()
  for (dir in directions) {
    if (identical(dir, "up")) {
      selected <- df[!is.na(df$.padj) & df$.padj < padj_cutoff & df$.lfc >= lfc_cutoff, , drop = FALSE]
    } else {
      selected <- df[!is.na(df$.padj) & df$.padj < padj_cutoff & df$.lfc <= -lfc_cutoff, , drop = FALSE]
    }
    if (nrow(selected) < 3) next
    orgdb <- orgdb_for(organism)
    sig_map <- map_symbols_to_entrez(selected[[symbol_col]], orgdb)
    all_map <- map_symbols_to_entrez(df[[symbol_col]], orgdb)
    if (nrow(sig_map) < 3) next
    ego <- suppressWarnings(clusterProfiler::enrichGO(
      gene = sig_map$ENTREZID,
      universe = all_map$ENTREZID,
      OrgDb = orgdb,
      ont = ontology,
      keyType = "ENTREZID",
      pAdjustMethod = "BH",
      pvalueCutoff = pvalue_cutoff,
      qvalueCutoff = qvalue_cutoff,
      readable = TRUE
    ))
    tab <- as.data.frame(ego)
    if (nrow(tab) == 0) next
    tab$direction <- dir
    results[[dir]] <- tab
  }

  if (length(results) == 0) {
    return(list(
      table = empty_enrich_table(),
      plot = NULL,
      messages = "No enriched terms passed the selected thresholds."
    ))
  }

  combined <- do.call(rbind, results)
  rownames(combined) <- NULL
  combined <- combined[order(combined$p.adjust), , drop = FALSE]

  plot <- NULL
  if (requireNamespace("ggplot2", quietly = TRUE) && nrow(combined) > 0) {
    plot <- tryCatch(
      enrich_dotplot(
        combined,
        top_n = top_n,
        title = title,
        by_direction = identical(direction, "both") &&
          length(unique(combined$direction)) > 1
      ),
      error = function(e) NULL
    )
  }

  list(table = combined, plot = plot, messages = NULL)
}

gsea_impl <- function(df, symbol_col, rank_col, organism = "mouse",
                      ontology = "BP", pvalue_cutoff = 0.05,
                      min_size = 10, max_size = 500, top_n = 20,
                      seed = 1, title = "GO gene set enrichment") {
  df <- as.data.frame(df, stringsAsFactors = FALSE)
  if (!symbol_col %in% names(df)) stop("Gene symbol column not found: ", symbol_col)
  if (!rank_col %in% names(df)) stop("Ranking column not found: ", rank_col)
  ranks <- suppressWarnings(as.numeric(df[[rank_col]]))
  symbols <- as.character(df[[symbol_col]])
  keep <- !is.na(ranks) & !is.na(symbols) & nzchar(symbols)
  ranks <- ranks[keep]
  symbols <- symbols[keep]
  if (length(ranks) < 100) stop("Fewer than 100 ranked genes; GSEA needs more.")
  ord <- order(ranks, decreasing = TRUE)
  rnk <- stats::setNames(ranks[ord], symbols[ord])
  rnk <- rnk[!duplicated(names(rnk))]
  rnk <- sort(rnk, decreasing = TRUE)

  orgdb <- orgdb_for(organism)
  set.seed(seed)
  gse <- suppressWarnings(clusterProfiler::gseGO(
    geneList = rnk,
    OrgDb = orgdb,
    ont = ontology,
    keyType = "SYMBOL",
    minGSSize = min_size,
    maxGSSize = max_size,
    pvalueCutoff = 1,
    verbose = FALSE,
    eps = 0,
    seed = TRUE
  ))
  tab <- as.data.frame(gse)
  if (nrow(tab) == 0) {
    return(list(table = empty_gsea_table(), plot = NULL,
                messages = "No GO gene sets were tested."))
  }
  tab <- tab[order(tab$p.adjust), , drop = FALSE]
  sig <- tab[!is.na(tab$p.adjust) & tab$p.adjust < pvalue_cutoff, , drop = FALSE]

  plot <- NULL
  if (nrow(sig) > 0 && requireNamespace("ggplot2", quietly = TRUE)) {
    plot <- tryCatch(
      gsea_dotplot(sig, top_n = top_n, title = title),
      error = function(e) NULL
    )
  }

  list(table = tab, plot = plot,
       messages = sprintf("%d gene sets tested, %d at p.adjust < %s",
                          nrow(tab), nrow(sig), pvalue_cutoff))
}

save_ma_plot <- function(df, x_col, y_col, outdir, name = "ma_plot", title = "MA plot") {
  df <- as.data.frame(df, stringsAsFactors = FALSE)
  df$.x <- suppressWarnings(as.numeric(df[[x_col]]))
  df$.y <- suppressWarnings(as.numeric(df[[y_col]]))
  df <- df[is.finite(df$.x) & is.finite(df$.y), , drop = FALSE]
  p <- ggplot2::ggplot(df, ggplot2::aes(x = .x, y = .y)) +
    ggplot2::geom_point(size = 1.2, alpha = 0.6, color = "grey35") +
    ggplot2::geom_hline(yintercept = 0, color = "#c2410c", linewidth = 0.4) +
    ggplot2::labs(x = x_col, y = y_col, title = title) +
    ggplot2::theme_bw(base_size = 12) +
    ggplot2::theme(panel.grid.minor = ggplot2::element_blank())
  save_plot(p, outdir, name, width = 6, height = 4.5)
}

kegg_organism_code <- function(organism) {
  organism <- tolower(organism %||% "mouse")
  if (organism %in% c("mouse", "mm", "mmusculus", "mus musculus")) return("mmu")
  if (organism %in% c("human", "hs", "hsapiens", "homo sapiens")) return("hsa")
  stop("Unsupported KEGG organism: ", organism)
}

safe_map_ids <- function(keys, keytype, orgdb) {
  keys <- as.character(keys)
  result <- rep(NA_character_, length(keys))
  valid <- !is.na(keys) & nzchar(keys)
  if (!any(valid)) return(result)
  unique_keys <- unique(keys[valid])
  mapped <- tryCatch(
    suppressMessages(AnnotationDbi::mapIds(
      orgdb, keys = unique_keys, column = "ENTREZID",
      keytype = keytype, multiVals = "first"
    )),
    error = function(e) NULL
  )
  if (is.null(mapped)) return(result)
  if (is.list(mapped)) {
    mapped <- vapply(mapped, function(x) {
      if (length(x) == 0 || is.na(x[[1]])) NA_character_ else as.character(x[[1]])
    }, character(1))
  } else {
    mapped <- as.character(mapped)
  }
  if (is.null(names(mapped))) names(mapped) <- unique_keys
  result[valid] <- unname(mapped[match(keys[valid], names(mapped))])
  result
}

map_to_entrez <- function(df, id_col, symbol_col, organism) {
  orgdb <- orgdb_for(organism)
  ids <- as.character(df[[id_col]])
  ens <- grepl("^ENS", ids)
  if (mean(ens, na.rm = TRUE) > 0.5) {
    ids <- sub("\\..*$", "", ids)
    keytype <- "ENSEMBL"
  } else {
    keytype <- "SYMBOL"
  }
  eid <- safe_map_ids(ids, keytype, orgdb)
  miss <- is.na(eid)
  if (any(miss) && symbol_col %in% names(df)) {
    eid[miss] <- safe_map_ids(df[[symbol_col]][miss], "SYMBOL", orgdb)
  }
  eid
}

gsea_kegg_impl <- function(df, mat, samples, id_col = "gene_id",
                           symbol_col = "gene_symbol", rank_col = "stat",
                           group_col = "group", organism = "mouse",
                           padj_cutoff = 0.05, pvalue_cutoff = 0.05,
                           min_size = 10, max_size = 500, top_n = 20,
                           pathways = character(), scale_method = "minmax",
                           group_labels = "", color_low = "#3B5998",
                           color_high = "#E42528", width = 0, height = 0,
                           seed = 1) {
  df <- as.data.frame(df, stringsAsFactors = FALSE)
  if (!"padj" %in% names(df)) stop("The DE table has no padj column.")
  if (!rank_col %in% names(df)) stop("Ranking column not found: ", rank_col)
  df <- df[!is.na(df$padj) & df$padj < padj_cutoff &
             !is.na(df[[rank_col]]), , drop = FALSE]
  if (nrow(df) == 0) stop("No significant genes at padj < ", padj_cutoff, ".")
  sig_df <- df[order(df[[rank_col]], decreasing = TRUE, na.last = TRUE), , drop = FALSE]
  sig_df$entrez <- map_to_entrez(sig_df, id_col, symbol_col, organism)

  gene_df <- sig_df[!is.na(sig_df$entrez), , drop = FALSE]
  gene_df <- gene_df[order(-abs(gene_df[[rank_col]])), , drop = FALSE]
  gene_df <- gene_df[!duplicated(gene_df$entrez), , drop = FALSE]
  if (nrow(gene_df) < 10) {
    return(list(
      table = empty_gsea_table(), significant = empty_gsea_table(),
      plot = NULL, heatmap = NULL,
      messages = sprintf("Only %d significant genes mapped to ENTREZ; KEGG GSEA needs at least 10.",
                         nrow(gene_df))
    ))
  }

  gene_list <- sort(stats::setNames(as.numeric(gene_df[[rank_col]]), gene_df$entrez),
                    decreasing = TRUE)
  set.seed(seed)
  gse_error <- NULL
  gse <- tryCatch(
    suppressWarnings(clusterProfiler::gseKEGG(
      geneList = gene_list,
      organism = kegg_organism_code(organism),
      pvalueCutoff = 1,
      minGSSize = min_size,
      maxGSSize = max_size,
      verbose = FALSE
    )),
    error = function(e) {
      gse_error <<- conditionMessage(e)
      NULL
    }
  )
  if (is.null(gse)) {
    return(list(
      table = empty_gsea_table(), significant = empty_gsea_table(),
      plot = NULL, heatmap = NULL,
      messages = paste("KEGG GSEA failed:", gse_error %||% "unknown error")
    ))
  }
  tab <- as.data.frame(gse)
  if (nrow(tab) == 0) {
    return(list(
      table = empty_gsea_table(), significant = empty_gsea_table(),
      plot = NULL, heatmap = NULL,
      messages = "KEGG GSEA returned no tested pathways."
    ))
  }
  tab <- tab[order(tab$p.adjust, -abs(tab$NES), na.last = TRUE), , drop = FALSE]
  sig <- tab[!is.na(tab$p.adjust) & tab$p.adjust < pvalue_cutoff, , drop = FALSE]

  selected <- character()
  if (length(pathways) && !all(is.na(pathways))) {
    selected <- trimws(unlist(strsplit(
      paste(pathways[!is.na(pathways)], collapse = ","), ","
    )))
    selected <- selected[!is.na(selected) & nzchar(selected)]
  }
  plot_tab <- sig
  if (length(selected)) {
    missing <- setdiff(selected, tab$ID)
    if (length(missing)) {
      warning("Requested KEGG pathways not tested: ", paste(missing, collapse = ", "))
    }
    plot_tab <- tab[tab$ID %in% selected, , drop = FALSE]
    if (nrow(plot_tab) == 0) plot_tab <- sig
  }
  plot <- NULL
  if (nrow(plot_tab) > 0 && requireNamespace("ggplot2", quietly = TRUE)) {
    plot <- tryCatch(
      gsea_dotplot(plot_tab, top_n = top_n, title = "KEGG GSEA"),
      error = function(e) NULL
    )
  }

  sample_ids <- as.character(samples$sample_id)
  mat <- align_samples(mat, samples)
  genes <- intersect(as.character(sig_df[[id_col]]), rownames(mat))
  heatmap <- NULL
  if (length(genes) >= 2) {
    m <- mat[genes, sample_ids, drop = FALSE]
    if (!group_col %in% names(samples)) stop("Group column not found: ", group_col)
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

    is_z <- identical(tolower(scale_method), "zscore")
    if (is_z) {
      m_scaled <- zscore_rows(m)
      legend_at <- c(-2, 0, 2)
      legend_labels <- c("-2", "0", "2")
    } else {
      m_scaled <- t(apply(m, 1, function(x) {
        rg <- diff(range(x, na.rm = TRUE))
        if (!is.finite(rg) || rg == 0) rep(0.5, length(x)) else (x - min(x, na.rm = TRUE)) / rg
      }))
      legend_at <- c(0, 0.5, 1)
      legend_labels <- c("Row min", "Row mid", "Row max")
    }
    row_info <- sig_df[match(genes, as.character(sig_df[[id_col]])), , drop = FALSE]
    labels <- if (symbol_col %in% names(row_info)) as.character(row_info[[symbol_col]]) else genes
    labels[is.na(labels) | !nzchar(labels)] <- genes[is.na(labels) | !nzchar(labels)]
    rownames(m_scaled) <- make.unique(labels)

    counts <- table(groups)
    shown <- levels(groups)
    if (length(group_labels) && !is.na(group_labels[1]) && nzchar(group_labels[1])) {
      custom <- trimws(unlist(strsplit(paste(group_labels, collapse = ","), ",")))
      custom <- custom[nzchar(custom)]
      if (length(custom) >= length(shown)) shown <- custom[seq_along(shown)]
    }
    shown_wrapped <- vapply(shown, function(x) {
      parts <- strsplit(x, " ", fixed = TRUE)[[1]]
      if (length(parts) >= 2) paste(parts[1], paste(parts[-1], collapse = " "), sep = "\n") else x
    }, character(1))
    col_labels <- sprintf("%s (n=%d)", shown_wrapped, as.integer(counts[levels(groups)]))
    col_split <- factor(groups, levels = levels(groups), labels = col_labels)
    col_fun <- circlize::colorRamp2(legend_at,
                                    c(color_low, "#F0F0F0", color_high))
    if (!is.finite(width) || width <= 0) width <- max(6.4, 0.45 * ncol(m_scaled) + 3)
    if (!is.finite(height) || height <= 0) height <- min(10, max(5, 0.12 * nrow(m_scaled) + 2.5))

    n_total <- nrow(sig_df)
    weights <- as.numeric(sig_df[[rank_col]])
    panel_ids <- unique(as.character(plot_tab$ID))
    if (length(panel_ids) < 2) {
      more <- tab$ID[order(tab$p.adjust, -abs(tab$NES), na.last = TRUE)]
      panel_ids <- unique(c(panel_ids, as.character(more)))
    }
    panel_ids <- head(panel_ids, 2)
    panel_tab <- tab[match(panel_ids, tab$ID), , drop = FALSE]
    panel_tab <- panel_tab[!is.na(panel_tab$ID), , drop = FALSE]

    pathway_entrez <- function(id) {
      row <- tab[match(id, tab$ID), , drop = FALSE]
      genes_in_pathway <- character()
      if (requireNamespace("KEGGREST", quietly = TRUE)) {
        genes_in_pathway <- tryCatch({
          g <- KEGGREST::keggGet(id)[[1]]$GENE
          grep("^[0-9]+$", g, value = TRUE)
        }, error = function(e) character())
      }
      if (!length(genes_in_pathway) && "core_enrichment" %in% names(row)) {
        genes_in_pathway <- unlist(strsplit(as.character(row$core_enrichment), "[/ ]+"))
        genes_in_pathway <- genes_in_pathway[nzchar(genes_in_pathway)]
      }
      genes_in_pathway
    }

    left_id <- right_id <- NULL
    if (nrow(panel_tab) > 0) {
      positive <- panel_tab$ID[!is.na(panel_tab$NES) & panel_tab$NES > 0]
      negative <- panel_tab$ID[!is.na(panel_tab$NES) & panel_tab$NES < 0]
      left_id <- if (length(positive)) positive[1] else panel_tab$ID[1]
      right_id <- if (length(negative)) negative[1] else if (nrow(panel_tab) > 1) panel_tab$ID[2] else NULL
      if (!is.null(right_id) && identical(right_id, left_id)) right_id <- NULL
    }
    hits_left <- if (is.null(left_id)) integer() else which(as.character(sig_df$entrez) %in% pathway_entrez(left_id))
    hits_right <- if (is.null(right_id)) integer() else which(as.character(sig_df$entrez) %in% pathway_entrez(right_id))
    es_left <- calc_gsea_curve(hits_left, n_total, weights)
    es_right <- abs(calc_gsea_curve(hits_right, n_total, weights))

    pw_label <- function(id) {
      row <- tab[match(id, tab$ID), , drop = FALSE]
      if (!nrow(row)) return(id)
      wrapped <- paste(strwrap(as.character(row$Description), width = 30), collapse = "\n")
      sprintf("%s: %s\np adj = %.1e", row$ID, wrapped, row$p.adjust)
    }
    pw_left <- if (is.null(left_id)) "" else pw_label(left_id)
    pw_right <- if (is.null(right_id)) "" else pw_label(right_id)

    left_ha <- if (!is.null(left_id)) {
      ComplexHeatmap::rowAnnotation(
        gsea_l = ComplexHeatmap::anno_empty(border = FALSE, width = grid::unit(2.6, "cm")),
        show_annotation_name = FALSE
      )
    } else NULL
    right_ha <- if (!is.null(right_id)) {
      ComplexHeatmap::rowAnnotation(
        gsea_r = ComplexHeatmap::anno_empty(border = FALSE, width = grid::unit(2.6, "cm")),
        show_annotation_name = FALSE
      )
    } else NULL

    heatmap <- ComplexHeatmap::Heatmap(
      m_scaled,
      name = "expr",
      col = col_fun,
      cluster_rows = FALSE,
      cluster_columns = FALSE,
      show_row_names = FALSE,
      show_column_names = FALSE,
      column_split = col_split,
      column_gap = grid::unit(0, "mm"),
      column_title_gp = grid::gpar(fontsize = 11.5),
      left_annotation = left_ha,
      right_annotation = right_ha,
      use_raster = FALSE,
      show_heatmap_legend = FALSE
    )

    decorate_gsea <- function() {
      if (!is.null(left_id)) {
        ComplexHeatmap::decorate_annotation("gsea_l", {
          grid::pushViewport(grid::viewport(xscale = c(0, 1), yscale = c(1, n_total), clip = "off"))
          grid::grid.rect(gp = grid::gpar(col = "grey85", fill = NA, lwd = 0.8))
          for (tk in seq(0, 1, by = 0.2)) {
            grid::grid.segments(1 - tk, n_total, 1 - tk, n_total * 1.015,
                                default.units = "native", gp = grid::gpar(col = "black"))
            grid::grid.segments(1 - tk, 1, 1 - tk, -n_total * 0.015,
                                default.units = "native", gp = grid::gpar(col = "black"))
          }
          for (yk in seq(0, 1, by = 0.2)) {
            yy <- 1 + yk * (n_total - 1)
            grid::grid.segments(0, yy, -0.03, yy, default.units = "native",
                                gp = grid::gpar(col = "black"))
          }
          grid::grid.lines(x = c(0, 0), y = c(1, n_total), default.units = "native",
                           gp = grid::gpar(col = "red", lty = "dashed", lwd = 1.5))
          grid::grid.lines(x = c(1, 1), y = c(1, n_total), default.units = "native",
                           gp = grid::gpar(col = "black", lwd = 1))
          if (length(hits_left)) {
            y_hits <- n_total - hits_left + 1
            grid::grid.segments(x0 = 1, y0 = y_hits, x1 = 0.92, y1 = y_hits,
                                default.units = "native", gp = grid::gpar(col = "black", lwd = 0.6))
          }
          grid::grid.lines(x = 1 - es_left, y = n_total:1, default.units = "native",
                           gp = grid::gpar(col = "green", lwd = 2))
          grid::grid.text(pw_left, x = grid::unit(0.18, "npc"), y = grid::unit(0.5, "npc"),
                          rot = 90, gp = grid::gpar(fontsize = 9.5, lineheight = 0.95))
          grid::popViewport()
        })
      }
      if (!is.null(right_id)) {
        ComplexHeatmap::decorate_annotation("gsea_r", {
          grid::pushViewport(grid::viewport(xscale = c(0, 1), yscale = c(1, n_total), clip = "off"))
          grid::grid.rect(gp = grid::gpar(col = "grey85", fill = NA, lwd = 0.8))
          for (tk in seq(0, 1, by = 0.2)) {
            grid::grid.segments(tk, n_total, tk, n_total * 1.015,
                                default.units = "native", gp = grid::gpar(col = "black"))
            grid::grid.segments(tk, 1, tk, -n_total * 0.015,
                                default.units = "native", gp = grid::gpar(col = "black"))
          }
          for (yk in seq(0, 1, by = 0.2)) {
            yy <- 1 + yk * (n_total - 1)
            grid::grid.segments(1, yy, 1.03, yy, default.units = "native",
                                gp = grid::gpar(col = "black"))
          }
          grid::grid.lines(x = c(1, 1), y = c(1, n_total), default.units = "native",
                           gp = grid::gpar(col = "red", lty = "dashed", lwd = 1.5))
          grid::grid.lines(x = c(0, 0), y = c(1, n_total), default.units = "native",
                           gp = grid::gpar(col = "black", lwd = 1))
          if (length(hits_right)) {
            y_hits <- n_total - hits_right + 1
            grid::grid.segments(x0 = 0, y0 = y_hits, x1 = 0.08, y1 = y_hits,
                                default.units = "native", gp = grid::gpar(col = "black", lwd = 0.6))
          }
          grid::grid.lines(x = es_right, y = n_total:1, default.units = "native",
                           gp = grid::gpar(col = "green", lwd = 2))
          grid::grid.text(pw_right, x = grid::unit(1.22, "npc"), y = grid::unit(0.5, "npc"),
                          rot = 90, gp = grid::gpar(fontsize = 9.5, lineheight = 0.95))
          grid::popViewport()
        })
      }
      ComplexHeatmap::decorate_heatmap_body("expr", column_slice = 1, {
        grid::pushViewport(grid::viewport(clip = "off"))
        n_bins <- 35
        bin_cols <- col_fun(seq(1, 0, length.out = n_bins))
        bin_edges <- seq(-0.15, 2.15, length.out = n_bins + 1)
        for (i in seq_len(n_bins)) {
          grid::grid.rect(
            x = grid::unit((bin_edges[i] + bin_edges[i + 1]) / 2, "npc"),
            y = grid::unit(-0.85, "cm"),
            width = grid::unit(bin_edges[i + 1] - bin_edges[i], "npc"),
            height = grid::unit(0.38, "cm"),
            gp = grid::gpar(fill = bin_cols[i], col = NA)
          )
        }
        lbls <- c("1", "0.8", "0.6", "0.4", "0.2", "0")
        lbl_x <- seq(-0.1, 2.1, length.out = 6)
        for (i in seq_along(lbls)) {
          grid::grid.text(lbls[i], x = grid::unit(lbl_x[i], "npc"),
                          y = grid::unit(-0.38, "cm"), gp = grid::gpar(fontsize = 11))
        }
        up <- sum(weights > 0, na.rm = TRUE)
        down <- sum(weights < 0, na.rm = TRUE)
        count_lab <- sprintf("Non-foamy MØ: %d   Foamy MØ: %d", up, down)
        grid::grid.text("Enriched genes", x = grid::unit(1, "npc"),
                        y = grid::unit(-1.45, "cm"), gp = grid::gpar(fontsize = 12.5))
        grid::grid.text(count_lab, x = grid::unit(1, "npc"),
                        y = grid::unit(-2.05, "cm"), gp = grid::gpar(fontsize = 12.5))
        grid::popViewport()
      })
    }

    heatmap <- list(object = heatmap, width = width, height = height,
                    n_genes = length(genes), decorate = decorate_gsea)
  }

  list(
    table = tab, significant = sig, plot = plot, heatmap = heatmap,
    messages = sprintf("%d significant genes mapped; %d KEGG pathways tested, %d at p.adjust < %s.",
                       nrow(sig_df), nrow(tab), nrow(sig), pvalue_cutoff)
  )
}
