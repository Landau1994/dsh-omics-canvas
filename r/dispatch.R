#!/usr/bin/env Rscript
# dispatch.R -- execute a single Omics Canvas node.
#
# Usage: Rscript dispatch.R <task.json> [result.json]
# The task JSON contains the node type, R function, params, input artifact
# paths and the output directory. The result is written as JSON so the
# Python engine can collect artifacts without parsing console output.

script_dir <- local({
  args <- commandArgs(trailingOnly = FALSE)
  match <- grep("^--file=", args, value = TRUE)
  if (length(match)) {
    dirname(normalizePath(sub("^--file=", "", match[1])))
  } else {
    getwd()
  }
})

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 1) {
  stop("Usage: dispatch.R <task.json> [result.json]")
}

task_path <- args[1]
task <- jsonlite::fromJSON(task_path, simplifyVector = FALSE)
if (is.null(task$outdir)) stop("Task is missing 'outdir'.")
dir.create(task$outdir, recursive = TRUE, showWarnings = FALSE)
result_path <- if (length(args) >= 2) args[2] else file.path(task$outdir, "result.json")

`%||%` <- function(a, b) {
  if (is.null(a)) return(b)
  if (length(a) == 0) return(b)
  if (length(a) == 1 && is.na(a)) return(b)
  a
}

source(file.path(script_dir, "common.R"))
r_file <- task$r_file %||% "common.R"
if (!file.exists(file.path(script_dir, r_file))) {
  stop("Node implementation not found: ", r_file)
}
source(file.path(script_dir, r_file))

# User overrides for built-in nodes are sourced after the built-in file so the
# function of the same name wins. Custom nodes normally have no override.
node_type <- task$type %||% task$node
override_file <- file.path(
  script_dir,
  "overrides",
  paste0(gsub("[^A-Za-z0-9_]", "_", node_type), ".R")
)
if (file.exists(override_file)) {
  source(override_file)
}

fn_name <- task$r_function
if (is.null(fn_name) || !exists(fn_name, mode = "function")) {
  stop("R function not found: ", fn_name)
}
fn <- get(fn_name, mode = "function")

messages <- character()
res <- tryCatch(
  withCallingHandlers(
    fn(task),
    message = function(m) {
      messages <<- c(messages, conditionMessage(m))
      invokeRestart("muffleMessage")
    },
    warning = function(w) {
      messages <<- c(messages, paste0("warning: ", conditionMessage(w)))
      invokeRestart("muffleWarning")
    }
  ),
  error = function(e) {
    list(
      ok = FALSE,
      error = conditionMessage(e),
      traceback = paste(utils::head(capture.output(traceback()), 40), collapse = "\n")
    )
  }
)

if (!is.list(res)) res <- list(ok = TRUE, messages = as.character(res))
if (is.null(res$ok)) res$ok <- TRUE
if (length(messages)) {
  res$messages <- c(as.character(res$messages %||% character()), messages)
}
res$node <- task$node

jsonlite::write_json(
  res,
  result_path,
  auto_unbox = TRUE,
  null = "null",
  na = "null",
  digits = NA,
  pretty = TRUE
)

if (!isTRUE(res$ok)) {
  quit(status = 1, save = "no")
}
