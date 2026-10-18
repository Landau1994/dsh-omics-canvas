/**
 * dsh-omics-canvas -- host half.
 *
 * Starts the existing Omics Canvas Python server (`python -m omics_canvas
 * serve`) on a private loopback port and proxies it under `/omics-canvas` on
 * the DSH web server. The browser panel is a same-origin iframe, so the canvas
 * keeps its own editor, run API and artifact URLs without a second public
 * port.
 *
 * The plugin owns the child process: unloading the row stops the server.
 */

import { spawn } from 'node:child_process'
import { createServer as createNetServer } from 'node:net'
import { request as httpRequest } from 'node:http'
import { request as httpsRequest } from 'node:https'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

export const name = 'dsh-omics-canvas'

const DEFAULT_PLUGIN_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')

const ROUTE_PREFIX = '/omics-canvas'

const DEFAULTS = {
  /** Directory that contains the `omics_canvas` Python package and `r/`. */
  pluginRoot: process.env.OMICS_CANVAS_ROOT || DEFAULT_PLUGIN_ROOT,
  /** Base directory for relative data paths in canvas graphs. */
  workdir: process.env.OMICS_CANVAS_WORKDIR || process.cwd(),
  /** Python interpreter that can import `omics_canvas` (PyYAML required). */
  python: 'python3',
  /** Conda environment used by the R nodes. */
  env: 'scptools',
  /** Run output directory; empty means `<pluginRoot>/runs`. */
  runsDir: '',
  /** Fixed local port; 0 asks the OS for a free port. */
  port: 0,
  /** External canvas URL. When set, no Python server is started. */
  canvasUrl: '',
  /** Set false to wait for an already-running server on `port`. */
  startServer: true,
  /** How long to wait for `/api/catalog` before failing the route. */
  readyTimeoutMs: 30000,
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function normaliseBase(url) {
  return String(url).replace(/\/+$/, '')
}

function findFreePort() {
  return new Promise((resolve, reject) => {
    const server = createNetServer()
    server.unref()
    server.once('error', reject)
    server.listen(0, '127.0.0.1', () => {
      const address = server.address()
      const port = typeof address === 'object' && address !== null ? address.port : 0
      server.close(() => resolve(port))
    })
  })
}

/**
 * Start the canvas server and expose a loopback base URL.
 * @param ctx - Cordis host context.
 * @param settings - resolved plugin configuration.
 */
export function apply(ctx, config = {}) {
  const settings = { ...DEFAULTS, ...(config || {}) }
  settings.port = Number(settings.port) || 0
  settings.readyTimeoutMs = Number(settings.readyTimeoutMs) || DEFAULTS.readyTimeoutMs
  const runsDir = settings.runsDir || `${settings.pluginRoot}/runs`

  const state = {
    child: null,
    baseUrl: null,
    stopping: false,
    logs: [],
  }
  let resolveReady
  let rejectReady
  const ready = new Promise((resolve, reject) => {
    resolveReady = resolve
    rejectReady = reject
  })
  // A failed startup is reported through proxy responses; keep the rejection
  // observed so an unused plugin row does not surface an unhandled rejection.
  ready.catch(() => {})

  const log = (level, message) => {
    try {
      const logger = ctx.logger
      if (logger && typeof logger[level] === 'function') logger[level](`[omics-canvas] ${message}`)
    } catch {
      /* logging must never break the plugin */
    }
  }

  const capture = (chunk) => {
    for (const line of String(chunk).split(/\r?\n/)) {
      if (!line.trim()) continue
      state.logs.push(line.trim())
    }
    if (state.logs.length > 80) state.logs.splice(0, state.logs.length - 80)
  }

  const stop = () => {
    state.stopping = true
    const child = state.child
    state.child = null
    if (!child || child.exitCode !== null) return
    try {
      child.kill('SIGTERM')
      const timer = setTimeout(() => {
        if (child.exitCode === null) child.kill('SIGKILL')
      }, 3000)
      if (typeof timer.unref === 'function') timer.unref()
    } catch (error) {
      log('warn', `could not stop the Python server: ${error instanceof Error ? error.message : String(error)}`)
    }
  }

  const waitForServer = async (baseUrl, signal) => {
    const deadline = Date.now() + settings.readyTimeoutMs
    while (Date.now() < deadline) {
      if (signal.aborted) throw new Error('startup cancelled')
      try {
        const controller = new AbortController()
        const timer = setTimeout(() => controller.abort(), 1500)
        const response = await fetch(`${baseUrl}/api/catalog`, { signal: controller.signal })
        clearTimeout(timer)
        if (response.ok) return
      } catch {
        /* retry until the deadline */
      }
      await sleep(250)
    }
    const tail = state.logs.slice(-6).join(' | ')
    throw new Error(`server did not become ready within ${settings.readyTimeoutMs}ms${tail ? `: ${tail}` : ''}`)
  }

  const start = async (signal) => {
    try {
      if (settings.canvasUrl) {
        state.baseUrl = normaliseBase(settings.canvasUrl)
        await waitForServer(state.baseUrl, signal)
        resolveReady()
        log('info', `using external canvas at ${state.baseUrl}`)
        return
      }

      const port = settings.port > 0 ? settings.port : await findFreePort()
      state.baseUrl = `http://127.0.0.1:${port}`

      if (settings.startServer) {
        const args = [
          '-m', 'omics_canvas', 'serve',
          '--host', '127.0.0.1',
          '--port', String(port),
          '--runs-dir', runsDir,
          '--workdir', settings.workdir,
          '--env', settings.env,
        ]
        const pythonPath = [settings.pluginRoot, process.env.PYTHONPATH]
          .filter((part) => typeof part === 'string' && part.length > 0)
          .join(':')
        const child = spawn(settings.python, args, {
          cwd: settings.pluginRoot,
          env: { ...process.env, PYTHONPATH: pythonPath },
          stdio: ['ignore', 'pipe', 'pipe'],
        })
        state.child = child
        child.stdout.on('data', capture)
        child.stderr.on('data', capture)
        child.once('error', (error) => {
          if (!state.stopping) log('error', `Python process error: ${error.message}`)
        })
        child.once('exit', (code, signalName) => {
          if (state.stopping) return
          log('warn', `Python server exited (code=${code}, signal=${signalName ?? 'none'})`)
        })
      }

      await waitForServer(state.baseUrl, signal)
      resolveReady()
      log('info', `canvas ready at ${state.baseUrl}`)
    } catch (error) {
      if (signal.aborted) return
      const message = error instanceof Error ? error.message : String(error)
      log('error', `startup failed: ${message}`)
      rejectReady(new Error(message))
    }
  }

  const sendError = (res, status, message) => {
    if (res.headersSent) {
      res.destroy()
      return
    }
    const body = JSON.stringify({ error: message })
    res.writeHead(status, {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store',
      'content-length': Buffer.byteLength(body),
    })
    res.end(body)
  }

  const proxy = async (req, res) => {
    const url = new URL(req.url || '/', 'http://dsh.omics.invalid')
    if (url.pathname !== ROUTE_PREFIX && !url.pathname.startsWith(`${ROUTE_PREFIX}/`)) {
      sendError(res, 404, 'not an Omics Canvas route')
      return
    }
    if (url.pathname === ROUTE_PREFIX) {
      res.writeHead(302, { location: `${ROUTE_PREFIX}/${url.search}` })
      res.end()
      return
    }

    let baseUrl
    try {
      await ready
      baseUrl = state.baseUrl
    } catch (error) {
      sendError(res, 503, error instanceof Error ? error.message : 'canvas server is not ready')
      return
    }

    const target = new URL(baseUrl)
    const pathname = url.pathname.startsWith(ROUTE_PREFIX)
      ? url.pathname.slice(ROUTE_PREFIX.length) || '/'
      : url.pathname
    const targetPath = `${pathname}${url.search}`
    const headers = { ...req.headers, host: target.host }
    const requestFn = target.protocol === 'https:' ? httpsRequest : httpRequest
    const upstream = requestFn({
      protocol: target.protocol,
      hostname: target.hostname,
      port: target.port || (target.protocol === 'https:' ? 443 : 80),
      path: targetPath,
      method: req.method,
      headers,
    }, (upstreamResponse) => {
      res.writeHead(upstreamResponse.statusCode || 502, upstreamResponse.headers)
      upstreamResponse.pipe(res)
    })

    upstream.once('error', (error) => {
      if (res.headersSent) res.destroy()
      else sendError(res, 502, `canvas proxy error: ${error.message}`)
    })
    req.once('aborted', () => upstream.destroy())
    req.pipe(upstream)
  }

  ctx.effect(() => {
    const controller = new AbortController()
    void start(controller.signal)
    return () => {
      controller.abort()
      stop()
    }
  }, 'dsh-omics-canvas: python server')

  ctx.inject(['webServer'], (webCtx) => {
    webCtx.effect(() => webCtx.webServer.register({
      kind: 'prefix',
      path: ROUTE_PREFIX,
      handler: proxy,
    }), 'dsh-omics-canvas: proxy route')
  })

  // Model-facing tools. They talk to the managed Python server through its
  // loopback base URL, so every tool uses the same validation, execution,
  // cache, report and custom-node APIs as the browser panel.
  const api = async (path, init = {}) => {
    await ready
    const response = await fetch(`${state.baseUrl}${path}`, {
      headers: { 'content-type': 'application/json', ...(init.headers || {}) },
      ...init,
    })
    const text = await response.text()
    let data
    try {
      data = text ? JSON.parse(text) : {}
    } catch {
      data = { status: response.status, text }
    }
    if (!response.ok) {
      const message = data && typeof data === 'object'
        ? (data.error || data.errors?.join('; ') || JSON.stringify(data))
        : String(data)
      throw new Error(message)
    }
    return data
  }

  const textOutput = {
    schema: { type: 'string' },
    render: (_args, value) => [{ type: 'text', text: String(value) }],
  }

  ctx.inject(['tools'], (toolCtx) => {
    const objectSchema = (properties, required = []) => ({
      type: 'object',
      properties,
      ...(required.length ? { required } : {}),
      additionalProperties: false,
    })

    const tool = (definition) => {
      try {
        toolCtx.tools.register({
          output: textOutput,
          ...definition,
        })
      } catch (error) {
        log('warn', `could not register ${definition.name}: ${error instanceof Error ? error.message : String(error)}`)
      }
    }

    tool({
      name: 'omics_canvas_catalog',
      description:
        'List the Omics Canvas node types (built-in and custom), their input/output ports and parameter schemas. Call this before building a graph.',
      parameters: objectSchema({}),
      execute: async () => JSON.stringify(await api('/api/catalog'), null, 2),
    })

    tool({
      name: 'omics_canvas_validate',
      description:
        'Validate an Omics Canvas graph without running it. A graph is {name, nodes:[{id,type,params,x,y}], edges:[{from,from_port,to,to_port}]}. Returns {valid, errors}.',
      parameters: objectSchema({
        graph: { type: 'object', additionalProperties: true, description: 'The canvas graph object to validate.' },
      }, ['graph']),
      execute: async (args) => JSON.stringify(
        await api('/api/validate', {
          method: 'POST',
          body: JSON.stringify({ graph: args.graph }),
        }),
        null,
        2,
      ),
    })

    tool({
      name: 'omics_canvas_run',
      description:
        'Run an Omics Canvas graph. Returns a run_id; poll omics_canvas_status until status is success or failed. Results are cached by node inputs, parameters and code.',
      parameters: objectSchema({
        graph: { type: 'object', additionalProperties: true, description: 'The canvas graph object to execute.' },
      }, ['graph']),
      execute: async (args) => JSON.stringify(
        await api('/api/run', {
          method: 'POST',
          body: JSON.stringify({ graph: args.graph }),
        }),
        null,
        2,
      ),
    })

    tool({
      name: 'omics_canvas_status',
      description:
        'Read a run manifest: per-node status, duration, cache hit, error, metrics and artifact URLs.',
      parameters: objectSchema({
        run_id: { type: 'string', description: 'Run id returned by omics_canvas_run.' },
      }, ['run_id']),
      execute: async (args) => {
        const manifest = await api(`/api/runs/${encodeURIComponent(args.run_id)}`)
        const nodes = {}
        for (const [nodeId, node] of Object.entries(manifest.nodes || {})) {
          nodes[nodeId] = {
            status: node.status,
            duration_s: node.duration_s,
            cache_hit: node.cache_hit,
            error: node.error,
            metrics: node.metrics,
            artifacts: Object.fromEntries(
              Object.entries(node.artifacts || {}).map(([port, artifact]) => [
                port,
                { label: artifact.label, path: artifact.path, url: artifact.url, type: artifact.type },
              ]),
            ),
          }
        }
        return JSON.stringify({
          run_id: manifest.run_id,
          status: manifest.status,
          total_duration_s: manifest.total_duration_s,
          cache: manifest.cache,
          error: manifest.error ?? null,
          nodes,
        }, null, 2)
      },
    })

    tool({
      name: 'omics_canvas_list_runs',
      description: 'List previous Omics Canvas runs with status and timestamps.',
      parameters: objectSchema({}),
      execute: async () => JSON.stringify(await api('/api/runs'), null, 2),
    })

    tool({
      name: 'omics_canvas_upsert_node',
      description:
        'Create or update a custom node. The node id must start with "custom.". Set language to "r" (default) or "python". R code defines run <- function(task); Python code defines def run(task). Both return {ok, artifacts, metrics, messages} with the same shape. A graph node may also set env to a conda environment.',
      parameters: objectSchema({
        node: {
          type: 'object',
          additionalProperties: true,
          description: 'Node definition: {id,language,title,description,inputs,outputs,params}.',
        },
        code: {
          type: 'string',
          description: "R or Python source defining run(task); see the tool description.",
        },
      }, ['node', 'code']),
      execute: async (args) => JSON.stringify(
        await api('/api/custom-nodes', {
          method: 'POST',
          body: JSON.stringify({ node: args.node, code: args.code }),
        }),
        null,
        2,
      ),
    })

    tool({
      name: 'omics_canvas_node_code',
      description:
        'Read or write a node implementation. Without code, returns the current custom code, override, or template. With code, saves an override for a built-in node or replaces a custom node implementation.',
      parameters: objectSchema({
        node_id: {
          type: 'string',
          description: 'Catalog node id, for example rna.filter or custom.my_node.',
        },
        code: {
          type: 'string',
          description: 'R or Python source to save. Omit to read.',
        },
      }, ['node_id']),
      execute: async (args) => {
        const path = `/api/nodes/${encodeURIComponent(args.node_id)}/code`
        const result = args.code === undefined
          ? await api(path)
          : await api(path, { method: 'PUT', body: JSON.stringify({ code: args.code }) })
        return JSON.stringify(result, null, 2)
      },
    })

    tool({
      name: 'omics_canvas_delete_node',
      description:
        'Delete a custom node and its R implementation. Built-in nodes cannot be deleted; reset their code instead.',
      parameters: objectSchema({
        node_id: { type: 'string', description: 'Custom node id, e.g. custom.my_node.' },
      }, ['node_id']),
      execute: async (args) => JSON.stringify(
        await api(`/api/custom-nodes/${encodeURIComponent(args.node_id)}`, { method: 'DELETE' }),
        null,
        2,
      ),
    })

    tool({
      name: 'omics_canvas_reset_node_code',
      description:
        'Remove an override from a built-in node and restore its shipped implementation.',
      parameters: objectSchema({
        node_id: { type: 'string', description: 'Built-in node id, e.g. rna.filter.' },
      }, ['node_id']),
      execute: async (args) => JSON.stringify(
        await api(`/api/nodes/${encodeURIComponent(args.node_id)}/code`, { method: 'DELETE' }),
        null,
        2,
      ),
    })

    tool({
      name: 'omics_canvas_cache',
      description: 'Inspect or clear the content-addressed node result cache.',
      parameters: objectSchema({
        action: {
          type: 'string',
          enum: ['stats', 'clear'],
          description: 'stats (default) or clear.',
        },
      }),
      execute: async (args) => {
        if (args.action === 'clear') {
          return JSON.stringify(await api('/api/cache', { method: 'DELETE' }), null, 2)
        }
        return JSON.stringify(await api('/api/cache'), null, 2)
      },
    })

    tool({
      name: 'omics_canvas_get_canvas',
      description:
        'Read the open canvas document by canvas_id. Returns {canvas_id, revision, graph}. The chat prompt includes the canvas_id when the user asks to edit a selected node.',
      parameters: objectSchema({
        canvas_id: { type: 'string', description: 'Canvas document id shown in the node-edit prompt.' },
      }, ['canvas_id']),
      execute: async (args) => JSON.stringify(
        await api(`/api/canvases/${encodeURIComponent(args.canvas_id)}`),
        null,
        2,
      ),
    })

    tool({
      name: 'omics_canvas_patch_canvas',
      description:
        'Patch the open canvas document. Ops: {op:"set_node_params",node_id,params,replace?}, {op:"update_node",node_id,patch:{label?,env?,type?}}, {op:"add_node",node}, {op:"remove_node",node_id}, {op:"add_edge",edge}, {op:"remove_edge",index}. Returns the updated graph and revision; the browser canvas polls and applies it.',
      parameters: objectSchema({
        canvas_id: { type: 'string', description: 'Canvas document id.' },
        ops: {
          type: 'array',
          description: 'Ordered patch operations, applied atomically.',
          items: { type: 'object', additionalProperties: true },
        },
      }, ['canvas_id', 'ops']),
      execute: async (args) => JSON.stringify(
        await api(`/api/canvases/${encodeURIComponent(args.canvas_id)}`, {
          method: 'PATCH',
          body: JSON.stringify({ ops: args.ops }),
        }),
        null,
        2,
      ),
    })

    tool({
      name: 'omics_canvas_read_artifact',
      description:
        'Read a run artifact. Text/TSV/CSV content is returned truncated; images and PDFs return a URL to open.',
      parameters: objectSchema({
        run_id: { type: 'string', description: 'Run id.' },
        path: {
          type: 'string',
          description: 'Artifact path relative to the run directory, e.g. de/de_results.tsv.',
        },
        max_chars: {
          type: 'integer',
          description: 'Maximum text characters to return (default 12000).',
        },
      }, ['run_id', 'path']),
      execute: async (args) => {
        const limit = Number.isFinite(args.max_chars) ? args.max_chars : 12000
        const url = `/omics-canvas/api/runs/${encodeURIComponent(args.run_id)}/files/${args.path
          .split('/')
          .map(encodeURIComponent)
          .join('/')}`
        const lower = String(args.path).toLowerCase()
        if (/\.(png|jpe?g|svg|webp|pdf)$/.test(lower)) {
          return JSON.stringify({ run_id: args.run_id, path: args.path, url, note: 'Binary artifact; open the URL.' }, null, 2)
        }
        await ready
        const response = await fetch(`${state.baseUrl}/api/runs/${encodeURIComponent(args.run_id)}/files/${args.path
          .split('/')
          .map(encodeURIComponent)
          .join('/')}`)
        const text = await response.text()
        if (!response.ok) throw new Error(text || `HTTP ${response.status}`)
        return text.length > limit
          ? `${text.slice(0, limit)}\n\n... truncated (${text.length - limit} characters omitted)`
          : text
      },
    })

    tool({
      name: 'omics_canvas_export_run',
      description:
        'Return publication/reproduction links for a run: an HTML report with figures and table previews, and a downloadable bundle with one R driver per node.',
      parameters: objectSchema({
        run_id: { type: 'string', description: 'Run id.' },
        format: {
          type: 'string',
          enum: ['report', 'bundle', 'both'],
          description: 'Which links to return (default both).',
        },
      }, ['run_id']),
      execute: async (args) => {
        const format = args.format || 'both'
        const base = `/omics-canvas/api/runs/${encodeURIComponent(args.run_id)}`
        return JSON.stringify({
          run_id: args.run_id,
          report: format === 'bundle' ? null : `${base}/report`,
          bundle: format === 'report' ? null : `${base}/export`,
          note: 'Open the report in a browser; the bundle is a ZIP with report.html, artifacts/, code/<node>.R and run_all.sh.',
        }, null, 2)
      },
    })
  })
}
