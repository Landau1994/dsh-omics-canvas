/* Omics Canvas -- dependency-free canvas editor for the node graph. */

(() => {
  "use strict";

  const NODE_W = 240;
  const HEADER_H = 36;
  const BODY_PAD = 8;
  const ROW_H = 24;

  const el = (id) => document.getElementById(id);
  const canvasWrap = el("canvas-wrap");
  const world = el("world");
  const svg = el("edges");
  const paletteList = el("palette-list");
  const inspector = el("inspector-body");
  const emptyHint = el("empty-hint");
  const runStatusEl = el("run-status");
  const zoomLabel = el("zoom-label");
  const graphNameInput = el("graph-name");
  const exampleSelect = el("example-select");
  const runsSelect = el("runs-select");
  const runButton = el("btn-run");

  const state = {
    catalog: null,
    specMap: {},
    categoryMap: {},
    graph: { name: "Untitled canvas", nodes: [], edges: [] },
    selection: null,
    camera: { x: 60, y: 30, scale: 1 },
    drag: null,
    connect: null,
    runId: null,
    manifest: null,
    pollTimer: null,
    saveTimer: null,
    nodeEls: new Map(),
    codeToken: 0,
    modalOpen: false,
    environments: [],
    environmentsLoaded: false,
    defaultEnv: "scptools",
    chatMessages: [],
    canvasId: null,
    canvasRevision: 0,
    canvasPollTimer: null,
    canvasSaveTimer: null,
    suppressCanvasSave: false,
    chatNodeType: null,
  };

  // ---------------------------------------------------------------- i18n
  const I18N = {
    en: {
      "brand.sub": "bulk RNA-seq / bulk proteomics",
      "toolbar.chat": "Chat",
      "toolbar.refresh": "Refresh",
      "toolbar.results": "Results",
      "toolbar.library": "Library",
      "toolbar.inspector": "Inspector",
      "toolbar.new": "New",
      "toolbar.import": "Import",
      "toolbar.export": "Export",
      "toolbar.fit": "Fit",
      "toolbar.run": "Run canvas",
      "toolbar.newNode": "+ New",
      "toolbar.previous": "Previous runs…",
      "toolbar.example": "Load example…",
      "palette.title": "Node library",
      "palette.search": "Search nodes…",
      "palette.hint": "Click a node to add it to the canvas. Drag from an output port to an input port to connect nodes.",
      "inspector.title": "Inspector",
      "inspector.empty": "Select a node to edit its parameters. Drag from an output port (right side) to an input port (left side) to connect nodes.",
      "inspector.runtime": "Runtime",
      "inspector.metrics": "Metrics",
      "inspector.messages": "Messages",
      "inspector.artifacts": "Artifacts",
      "inspector.parameters": "Parameters",
      "inspector.environment": "Conda environment",
      "inspector.environmentLabel": "Runtime environment",
      "inspector.environmentHelp": "R and Python nodes both run in the selected conda environment. The default comes from the server/plugin config.",
      "inspector.code": "Code",
      "empty.title": "Build a canvas",
      "empty.body": "Pick nodes from the left, connect them, then press Run canvas.",
      "status.pending": "pending",
      "status.running": "running",
      "status.success": "success",
      "status.failed": "failed",
      "status.skipped": "skipped",
      "status.cached": "cached",
      "run.idle": "idle",
      "run.starting": "starting…",
      "run.running": "running {done}/{total}",
      "run.invalid": "invalid graph",
      "run.requestFailed": "request failed",
      "run.report": "Report",
      "run.bundle": "Bundle (.zip)",
      "run.cache": "cache {hits} hit / {misses} miss",
      "code.loading": "Loading node code…",
      "code.custom": "Custom {language} node code. Saving edits the implementation used by every graph with this node.",
      "code.override": "Override active. Reset removes it and restores the built-in implementation.",
      "code.template": "Built-in node. Saving writes an override; the shipped source stays untouched.",
      "code.save": "Save code",
      "code.saving": "Saving…",
      "code.saved": "Saved.",
      "code.reset": "Reset override",
      "code.resetDone": "Override removed.",
      "code.editDefinition": "Edit definition",
      "code.deleteNode": "Delete node",
      "code.clone": "Clone ports as custom",
      "code.key": "key {key}",
      "code.previewTable": "Preview table",
      "code.hidePreview": "Hide preview",
      "code.openLog": "open node log",
      "results.title": "Run outputs",
      "results.empty": "Run the canvas, or load a previous run from the toolbar, to browse its outputs.",
      "results.cache": "Node cache",
      "results.clearCache": "Clear cache",
      "results.cleared": "Cleared {n} entries.",
      "results.cacheStats": "{n} entries · {mb} MB · {dir}",
      "modal.newNode": "New custom node",
      "modal.editNode": "Edit custom node",
      "modal.id": "Node id",
      "modal.language": "Language",
      "modal.title": "Title",
      "modal.description": "Description",
      "modal.inputs": "Inputs",
      "modal.outputs": "Outputs",
      "modal.params": "Parameters (JSON)",
      "modal.code": "R/Python code",
      "modal.cancel": "Cancel",
      "modal.create": "Create node",
      "modal.save": "Save node",
      "modal.saving": "Saving…",
      "modal.idHelp": "Must start with 'custom.'. R code lives under r/custom/, Python under py/custom/.",
      "modal.inputsHelp": "Comma-separated ports as id:type (matrix, table, plot, any). Example: expr:matrix, samples:table",
      "modal.outputsHelp": "Each output port must match an artifact key returned by run().",
      "modal.paramsHelp": "Array of {name,label,type,default,required,help,options}.",
      "chat.title": "Canvas assistant",
      "chat.note": "Prompts are sent to the current DSH agent. Replies appear in the DSH conversation.",
      "chat.placeholder": "Ask the agent to build, edit or run a graph…",
      "chat.send": "Send",
      "chat.open": "Open DSH conversation",
      "chat.sent": "Sent to the DSH agent. Open the conversation to read the reply.",
      "chat.unavailable": "This canvas is not embedded in DSH, so chat is unavailable. Open it from the DSH sidebar.",
      "chat.quickRna": "RNA-seq: GSE116271 foam vs non-foam, PCA + volcano + GO",
      "chat.quickProt": "Proteomics: PXD046756 exMM vs BV2, PCA + limma",
      "chat.you": "You",
      "chat.agent": "Agent",
      "chat.status": "Sent. Waiting for the agent…",
      "chat.error": "Could not send: {message}",
    }
  };

function t(key, vars = {}) {
    const text = I18N.en[key] ?? key;
    return text.replace(/\{(\w+)\}/g, (_match, name) => String(vars[name] ?? ""));
  }

  function specTitle(spec) {
    return spec ? spec.title : "";
  }

  function categoryLabel(category) {
    return category ? category.label : "";
  }

  // ---------------------------------------------------------------- helpers
  const escapeHtml = (value) =>
    String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");

  async function apiJson(path, options = {}) {
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    const text = await response.text();
    let data = null;
    try {
      data = text ? JSON.parse(text) : {};
    } catch {
      data = { error: text };
    }
    if (!response.ok) {
      throw new Error(data?.error || `HTTP ${response.status}`);
    }
    return data;
  }

  function showToast(message, isError = false) {
    const toast = document.createElement("div");
    toast.className = `toast${isError ? " err" : ""}`;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3200);
  }

  async function refreshCatalog() {
    const catalog = await fetch("api/catalog").then((response) => response.json());
    state.catalog = catalog;
    state.specMap = Object.fromEntries(catalog.nodes.map((spec) => [spec.id, spec]));
    state.categoryMap = Object.fromEntries(
      catalog.categories.map((category) => [category.id, category]),
    );
    buildPalette();
    renderNodes();
    renderEdges();
    renderInspector();
  }

  const uid = (prefix) => {
    let i = 1;
    while (state.graph.nodes.some((n) => n.id === `${prefix}_${i}`)) i += 1;
    return `${prefix}_${i}`;
  };

  const specOf = (type) => state.specMap[type];

  const nodeById = (id) => state.graph.nodes.find((n) => n.id === id);

  function categoryColor(categoryId) {
    return state.categoryMap[categoryId]?.color || "#64748b";
  }

  function defaultParams(spec) {
    const params = {};
    for (const p of spec.params || []) {
      if (p.default !== null && p.default !== undefined) params[p.name] = p.default;
    }
    return params;
  }

  function mergeDefaults(spec, params) {
    const merged = defaultParams(spec);
    for (const [key, value] of Object.entries(params || {})) {
      merged[key] = value;
    }
    return merged;
  }

  function screenToWorld(clientX, clientY) {
    const rect = canvasWrap.getBoundingClientRect();
    return {
      x: (clientX - rect.left - state.camera.x) / state.camera.scale,
      y: (clientY - rect.top - state.camera.y) / state.camera.scale,
    };
  }

  function portPosition(node, portId, kind) {
    const spec = specOf(node.type);
    if (!spec) return { x: node.x, y: node.y };
    const list = kind === "in" ? spec.inputs : spec.outputs;
    const index = Math.max(0, list.findIndex((p) => p.id === portId));
    return {
      x: node.x + (kind === "in" ? 0 : NODE_W),
      y: node.y + HEADER_H + BODY_PAD + index * ROW_H + ROW_H / 2,
    };
  }

  function edgePath(x1, y1, x2, y2) {
    const dx = Math.max(48, Math.abs(x2 - x1) * 0.5);
    return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
  }

  // ---------------------------------------------------------------- camera
  function applyCamera() {
    const { x, y, scale } = state.camera;
    world.style.transform = `translate(${x}px, ${y}px) scale(${scale})`;
    zoomLabel.textContent = `${Math.round(scale * 100)}%`;
  }

  function fitView() {
    const nodes = state.graph.nodes;
    if (!nodes.length) {
      state.camera = { x: 60, y: 30, scale: 1 };
      applyCamera();
      return;
    }
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    for (const node of nodes) {
      const spec = specOf(node.type);
      const ports = Math.max(spec?.inputs?.length || 0, spec?.outputs?.length || 0);
      const height = HEADER_H + BODY_PAD * 2 + ports * ROW_H;
      minX = Math.min(minX, node.x);
      minY = Math.min(minY, node.y);
      maxX = Math.max(maxX, node.x + NODE_W);
      maxY = Math.max(maxY, node.y + height);
    }
    const rect = canvasWrap.getBoundingClientRect();
    const width = Math.max(1, maxX - minX);
    const height = Math.max(1, maxY - minY);
    const scale = Math.min(
      Math.max(Math.min((rect.width - 120) / width, (rect.height - 120) / height), 0.3),
      1.25,
    );
    state.camera = {
      x: (rect.width - width * scale) / 2 - minX * scale,
      y: (rect.height - height * scale) / 2 - minY * scale,
      scale,
    };
    applyCamera();
  }

  // ---------------------------------------------------------------- palette
  function buildPalette() {
    const query = (el("palette-search").value || "").toLowerCase().trim();
    paletteList.innerHTML = "";
    for (const category of state.catalog.categories) {
      const specs = state.catalog.nodes.filter(
        (spec) =>
          spec.category === category.id &&
          (!query ||
            specTitle(spec).toLowerCase().includes(query) ||
            spec.id.toLowerCase().includes(query)),
      );
      if (!specs.length) continue;
      const group = document.createElement("div");
      group.className = "palette-group";
      group.innerHTML = `<div class="palette-group-title">
        <span class="cat-dot" style="background:${category.color}"></span>${escapeHtml(categoryLabel(category))}
      </div>`;
      for (const spec of specs) {
        const item = document.createElement("div");
        item.className = "palette-item";
        item.innerHTML = `<div class="pi-title">${escapeHtml(specTitle(spec))}</div>
          <div class="pi-desc">${escapeHtml(spec.description || "")}</div>`;
        item.addEventListener("click", () => addNode(spec.id));
        group.appendChild(item);
      }
      paletteList.appendChild(group);
    }
  }

  function addNode(type) {
    const spec = specOf(type);
    if (!spec) return;
    const rect = canvasWrap.getBoundingClientRect();
    const x = (rect.width / 2 - state.camera.x) / state.camera.scale - NODE_W / 2;
    const y = (rect.height / 2 - state.camera.y) / state.camera.scale - 50;
    const node = {
      id: uid(type.replaceAll(".", "_")),
      type,
      params: defaultParams(spec),
      x: Math.round(x / 8) * 8,
      y: Math.round(y / 8) * 8,
    };
    state.graph.nodes.push(node);
    state.selection = { kind: "node", id: node.id };
    renderAll();
  }

  // ---------------------------------------------------------------- render
  function renderAll() {
    renderNodes();
    renderEdges();
    renderInspector();
    toggleEmptyHint();
    scheduleSave();
  }

  function renderNodes() {
    for (const nodeEl of state.nodeEls.values()) nodeEl.remove();
    state.nodeEls.clear();

    for (const node of state.graph.nodes) {
      const spec = specOf(node.type);
      if (!spec) continue;
      const nodeEl = document.createElement("div");
      nodeEl.className = "node";
      nodeEl.dataset.id = node.id;
      nodeEl.style.left = `${node.x}px`;
      nodeEl.style.top = `${node.y}px`;

      const selected = state.selection?.kind === "node" && state.selection.id === node.id;
      if (selected) nodeEl.classList.add("selected");

      nodeEl.innerHTML = `
        <div class="node-header">
          <span class="cat-dot" style="background:${categoryColor(spec.category)}"></span>
          <span class="node-title">${escapeHtml(specTitle(spec))}</span>
          <span class="node-status"></span>
        </div>
        <div class="node-body">
          <div class="port-col inputs">
            ${(spec.inputs || [])
              .map(
                (port) =>
                  `<div class="port-row"><span>${escapeHtml(port.label)}</span>
                   <span class="port-dot input" data-port="${escapeHtml(port.id)}"></span></div>`,
              )
              .join("")}
          </div>
          <div class="port-col outputs">
            ${(spec.outputs || [])
              .map(
                (port) =>
                  `<div class="port-row"><span>${escapeHtml(port.label)}</span>
                   <span class="port-dot output" data-port="${escapeHtml(port.id)}"></span></div>`,
              )
              .join("")}
          </div>
        </div>`;

      nodeEl.addEventListener("pointerdown", (event) => {
        if (event.target.closest(".port-dot")) return;
        if (event.button !== 0) return;
        selectNode(node.id);
        const point = screenToWorld(event.clientX, event.clientY);
        state.drag = {
          kind: "node",
          node,
          dx: node.x - point.x,
          dy: node.y - point.y,
        };
        canvasWrap.classList.add("panning");
        event.preventDefault();
      });

      nodeEl.querySelectorAll(".port-dot").forEach((dot) => {
        const kind = dot.classList.contains("input") ? "in" : "out";
        if (kind === "in") {
          dot.addEventListener("pointerup", (event) => {
            if (!state.connect) return;
            finishConnection(event, node, dot.dataset.port);
          });
        }
        dot.addEventListener("pointerdown", (event) => {
          event.stopPropagation();
          event.preventDefault();
          if (kind !== "out" || event.button !== 0) return;
          startConnection(node, dot.dataset.port);
        });
      });

      state.nodeEls.set(node.id, nodeEl);
      world.appendChild(nodeEl);
    }

    if (state.manifest) applyManifestStatuses();
  }

  function renderEdges() {
    svg.innerHTML = "";
    state.graph.edges.forEach((edge, index) => {
      const source = nodeById(edge.from);
      const target = nodeById(edge.to);
      if (!source || !target) return;
      const start = portPosition(source, edge.from_port, "out");
      const end = portPosition(target, edge.to_port, "in");
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", edgePath(start.x, start.y, end.x, end.y));
      path.setAttribute("class", "edge");
      if (state.selection?.kind === "edge" && state.selection.index === index) {
        path.classList.add("selected");
      }
      path.addEventListener("click", (event) => {
        event.stopPropagation();
        state.selection = { kind: "edge", index };
        renderEdges();
        renderInspector();
      });
      svg.appendChild(path);
    });

    if (state.connect) {
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute(
        "d",
        edgePath(
          state.connect.start.x,
          state.connect.start.y,
          state.connect.current.x,
          state.connect.current.y,
        ),
      );
      path.setAttribute("class", "edge temp");
      svg.appendChild(path);
    }
  }

  function applyManifestStatuses() {
    const nodes = state.manifest?.nodes || {};
    for (const [id, nodeEl] of state.nodeEls.entries()) {
      const status = nodes[id]?.status || "pending";
      nodeEl.classList.remove(
        "status-pending",
        "status-running",
        "status-success",
        "status-failed",
        "status-skipped",
      );
      nodeEl.classList.add(`status-${status}`);
      nodeEl.classList.toggle("cache-hit", Boolean(nodes[id]?.cache_hit));
    }
  }

  function toggleEmptyHint() {
    emptyHint.classList.toggle("hidden", state.graph.nodes.length > 0);
  }

  // ---------------------------------------------------------------- selection
  function selectNode(id) {
    if (state.selection?.kind === "node" && state.selection.id === id) return;
    state.selection = { kind: "node", id };
    for (const [nodeId, nodeEl] of state.nodeEls.entries()) {
      nodeEl.classList.toggle("selected", nodeId === id);
    }
    renderEdges();
    renderInspector();
  }

  function clearSelection() {
    state.selection = null;
    for (const nodeEl of state.nodeEls.values()) nodeEl.classList.remove("selected");
    renderEdges();
    renderInspector();
  }

  function deleteSelection() {
    if (!state.selection) return;
    if (state.selection.kind === "node") {
      const id = state.selection.id;
      state.graph.nodes = state.graph.nodes.filter((n) => n.id !== id);
      state.graph.edges = state.graph.edges.filter((e) => e.from !== id && e.to !== id);
    } else if (state.selection.kind === "edge") {
      state.graph.edges.splice(state.selection.index, 1);
    }
    state.selection = null;
    renderAll();
  }

  // ---------------------------------------------------------------- connect
  function startConnection(node, portId) {
    const start = portPosition(node, portId, "out");
    state.connect = {
      from: node.id,
      fromPort: portId,
      start,
      current: { ...start },
    };
    renderEdges();
  }

  function finishConnection(event, targetNode, targetPort) {
    const connect = state.connect;
    state.connect = null;
    if (!connect) return;
    if (connect.from === targetNode.id) {
      renderEdges();
      return;
    }
    const fromSpec = specOf(nodeById(connect.from)?.type);
    const toSpec = specOf(targetNode.type);
    const outPort = fromSpec?.outputs.find((p) => p.id === connect.fromPort);
    const inPort = toSpec?.inputs.find((p) => p.id === targetPort);
    if (!outPort || !inPort || outPort.type !== inPort.type) {
      renderEdges();
      return;
    }
    state.graph.edges = state.graph.edges.filter(
      (edge) => !(edge.to === targetNode.id && edge.to_port === targetPort),
    );
    state.graph.edges.push({
      from: connect.from,
      from_port: connect.fromPort,
      to: targetNode.id,
      to_port: targetPort,
    });
    renderEdges();
    scheduleSave();
  }

  // ---------------------------------------------------------------- inspector
  function renderInspector() {
    inspector.innerHTML = "";
    if (state.manifest) {
      inspector.appendChild(buildRunBanner());
    }

    if (!state.selection) {
      const hint = document.createElement("div");
      hint.className = "muted";
      hint.textContent = t("inspector.empty");
      inspector.appendChild(hint);
      inspector.appendChild(buildEdgeSection());
      return;
    }

    if (state.selection.kind === "edge") {
      inspector.appendChild(buildEdgeInspector());
      return;
    }

    const node = nodeById(state.selection.id);
    if (!node) return;
    const spec = specOf(node.type);
    if (!spec) {
      inspector.innerHTML = `<div class="error-box">Unknown node type: ${escapeHtml(node.type)}</div>`;
      return;
    }

    const title = document.createElement("div");
    title.className = "insp-title";
    title.textContent = specTitle(spec);
    inspector.appendChild(title);

    const agentRow = document.createElement("div");
    agentRow.className = "insp-agent-row";
    const agentButton = document.createElement("button");
    agentButton.type = "button";
    agentButton.className = "btn ghost mini";
    agentButton.textContent = "Edit with agent";
    agentButton.addEventListener("click", editSelectedNodeWithAgent);
    agentRow.appendChild(agentButton);
    inspector.appendChild(agentRow);

    const type = document.createElement("div");
    type.className = "insp-type";
    type.textContent = `${spec.id} · ${state.categoryMap[spec.category]?.label || spec.category}`;
    inspector.appendChild(type);

    if (spec.description) {
      const desc = document.createElement("div");
      desc.className = "insp-desc";
      desc.textContent = spec.description;
      inspector.appendChild(desc);
    }

    const record = state.manifest?.nodes?.[node.id];
    if (record) {
      inspector.appendChild(buildNodeStatus(record));
      if (record.error) {
        const box = document.createElement("div");
        box.className = "error-box";
        box.textContent = record.error;
        inspector.appendChild(box);
      }
      if (record.metrics && Object.keys(record.metrics).length) {
        inspector.appendChild(buildMetrics(record.metrics));
      }
      if (record.messages && record.messages.length) {
        const section = document.createElement("div");
        section.className = "insp-section";
        section.innerHTML = `<div class="insp-section-title">${escapeHtml(t("inspector.messages"))}</div>
          <ul class="messages">${record.messages
            .map((m) => `<li>${escapeHtml(m)}</li>`)
            .join("")}</ul>`;
        inspector.appendChild(section);
      }
      const artifacts = Object.values(record.artifacts || {});
      if (artifacts.length) {
        const section = document.createElement("div");
        section.className = "insp-section";
        section.innerHTML = `<div class="insp-section-title">${escapeHtml(t("inspector.artifacts"))}</div>`;
        for (const artifact of artifacts) {
          section.appendChild(buildArtifact(artifact, record.log));
        }
        inspector.appendChild(section);
      }
    }

    const paramsSection = document.createElement("div");
    paramsSection.className = "insp-section";
    paramsSection.innerHTML = `<div class="insp-section-title">${escapeHtml(t("inspector.parameters"))}</div>`;
    for (const param of spec.params || []) {
      paramsSection.appendChild(buildParamField(node, param));
    }
    inspector.appendChild(paramsSection);
    inspector.appendChild(buildEnvironmentSection(node));
    inspector.appendChild(buildCodeSection(node, spec));
  }

  async function ensureEnvironments() {
    if (state.environmentsLoaded) return;
    try {
      const data = await apiJson("api/environments");
      state.environments = data.environments || [];
      state.defaultEnv = data.default || "scptools";
      state.environmentsLoaded = true;
    } catch {
      state.environments = [];
      state.environmentsLoaded = true;
    }
  }

  function buildEnvironmentSection(node) {
    const section = document.createElement("div");
    section.className = "insp-section";
    section.innerHTML = `<div class="insp-section-title">${escapeHtml(t("inspector.environment"))}</div>`;
    const field = document.createElement("div");
    field.className = "field";
    const label = document.createElement("label");
    label.textContent = t("inspector.environmentLabel");
    const select = document.createElement("select");
    const renderOptions = () => {
      const current = node.env || "";
      select.innerHTML = "";
      const fallback = document.createElement("option");
      fallback.value = "";
      fallback.textContent = `default (${state.defaultEnv})`;
      select.appendChild(fallback);
      for (const env of state.environments) {
        const option = document.createElement("option");
        option.value = env;
        option.textContent = env;
        select.appendChild(option);
      }
      select.value = state.environments.includes(current) ? current : "";
    };
    renderOptions();
    select.addEventListener("change", () => {
      node.env = select.value || null;
      scheduleSave();
      showToast(select.value ? `Node environment: ${select.value}` : "Node uses the default environment.");
    });
    field.append(label, select);
    const help = document.createElement("div");
    help.className = "help";
    help.textContent = t("inspector.environmentHelp");
    field.appendChild(help);
    section.appendChild(field);
    if (!state.environmentsLoaded) {
      ensureEnvironments().then(() => {
        state.defaultEnv = state.defaultEnv || "scptools";
        renderOptions();
      });
    }
    return section;
  }

  function buildCodeSection(node, spec) {
    const section = document.createElement("div");
    section.className = "insp-section code-section";
    const heading = document.createElement("div");
    heading.className = "insp-section-title";
    heading.textContent = t("inspector.code");
    const note = document.createElement("div");
    note.className = "code-note";
    note.textContent = t("code.loading");
    const textarea = document.createElement("textarea");
    textarea.spellcheck = false;
    const actions = document.createElement("div");
    actions.className = "code-actions";
    const status = document.createElement("div");
    status.className = "code-status";
    section.append(heading, note, textarea, actions, status);

    const token = ++state.codeToken;
    let current = null;

    const setNote = (data) => {
      if (data.kind === "custom") {
        note.textContent = t("code.custom", { language: data.language || "r" });
      } else if (data.kind === "override") {
        note.textContent = t("code.override");
      } else {
        note.textContent = t("code.template");
      }
    };

    const rebuildActions = () => {
      actions.innerHTML = "";
      const save = document.createElement("button");
      save.className = "btn primary mini";
      save.textContent = t("code.save");
      save.addEventListener("click", async () => {
        save.disabled = true;
        status.className = "code-status";
        status.textContent = t("code.saving");
        try {
          const data = await apiJson(`api/nodes/${encodeURIComponent(node.type)}/code`, {
            method: "PUT",
            body: JSON.stringify({ code: textarea.value }),
          });
          current = data;
          setNote(data);
          rebuildActions();
          status.className = "code-status ok";
          status.textContent = t("code.saved");
          showToast(t("code.saved"));
        } catch (error) {
          status.className = "code-status err";
          status.textContent = error.message || String(error);
        } finally {
          save.disabled = false;
        }
      });
      actions.appendChild(save);
      const reload = document.createElement("button");
      reload.className = "btn ghost mini";
      reload.type = "button";
      reload.textContent = "Reload code";
      reload.addEventListener("click", () => renderInspector());
      actions.appendChild(reload);

      if (current?.builtin && current?.has_override) {
        const reset = document.createElement("button");
        reset.className = "btn ghost mini";
        reset.textContent = t("code.reset");
        reset.addEventListener("click", async () => {
          try {
            const data = await apiJson(`api/nodes/${encodeURIComponent(node.type)}/code`, {
              method: "DELETE",
            });
            current = data;
            textarea.value = data.code || "";
            setNote(data);
            rebuildActions();
            status.className = "code-status ok";
            status.textContent = t("code.resetDone");
          } catch (error) {
            status.className = "code-status err";
            status.textContent = error.message || String(error);
          }
        });
        actions.appendChild(reset);
      }

      if (!spec.custom) {
        const clone = document.createElement("button");
        clone.className = "btn ghost mini";
        clone.textContent = t("code.clone");
        clone.addEventListener("click", () => {
          openCustomNodeModal(null, {
            title: `${spec.title} custom`,
            language: "r",
            inputs: spec.inputs,
            outputs: spec.outputs,
            params: spec.params,
            code: defaultCustomCode("r"),
          });
        });
        actions.appendChild(clone);
      }

      if (spec.custom) {
        const edit = document.createElement("button");
        edit.className = "btn ghost mini";
        edit.textContent = t("code.editDefinition");
        edit.addEventListener("click", () => openCustomNodeModal(spec));
        actions.appendChild(edit);

        const remove = document.createElement("button");
        remove.className = "btn ghost mini";
        remove.textContent = t("code.deleteNode");
        remove.addEventListener("click", async () => {
          if (!window.confirm(`Delete custom node ${node.type}?`)) return;
          try {
            await apiJson(`api/custom-nodes/${encodeURIComponent(node.type)}`, {
              method: "DELETE",
            });
            state.graph.nodes = state.graph.nodes.filter((n) => n.id !== node.id);
            state.graph.edges = state.graph.edges.filter(
              (edge) => edge.from !== node.id && edge.to !== node.id,
            );
            state.selection = null;
            await refreshCatalog();
            renderAll();
            showToast("Custom node deleted.");
          } catch (error) {
            showToast(error.message || String(error), true);
          }
        });
        actions.appendChild(remove);
      }
    };

    apiJson(`api/nodes/${encodeURIComponent(node.type)}/code`)
      .then((data) => {
        if (token !== state.codeToken) return;
        current = data;
        textarea.value = data.code || "";
        setNote(data);
        rebuildActions();
      })
      .catch((error) => {
        if (token !== state.codeToken) return;
        note.textContent = `Could not load code: ${error.message || error}`;
      });

    return section;
  }

  function buildRunBanner() {
    const banner = document.createElement("div");
    const status = state.manifest.status || "unknown";
    banner.className = `run-banner ${status}`;
    const runId = state.manifest.run_id || state.runId || "";
    const counts = Object.values(state.manifest.nodes || {}).reduce(
      (acc, node) => {
        acc[node.status] = (acc[node.status] || 0) + 1;
        return acc;
      },
      {},
    );
    const cache = state.manifest.cache || {};
    banner.innerHTML = `<b>${escapeHtml(t("results.title"))} ${escapeHtml(runId)}</b><br/>
      ${escapeHtml(t(`status.${status}`))} · ${counts.success || 0} ok · ${counts.failed || 0} failed · ${
        counts.skipped || 0
      } skipped · ${state.manifest.total_duration_s ?? 0}s
      ${cache.enabled ? `· ${escapeHtml(t("run.cache", { hits: cache.hits || 0, misses: cache.misses || 0 }))}` : ""}
      <div class="run-links">
        <a href="api/runs/${encodeURIComponent(runId)}/report" target="_blank" rel="noopener">${escapeHtml(t("run.report"))}</a>
        <a href="api/runs/${encodeURIComponent(runId)}/export" target="_blank" rel="noopener">${escapeHtml(t("run.bundle"))}</a>
      </div>`;
    if (state.manifest.error) {
      banner.innerHTML += `<div class="error-box" style="margin-top:6px">${escapeHtml(
        state.manifest.error,
      )}</div>`;
    }
    return banner;
  }

  function buildNodeStatus(record) {
    const section = document.createElement("div");
    section.className = "insp-section";
    const duration =
      record.duration_s !== null && record.duration_s !== undefined
        ? `${record.duration_s}s`
        : "";
    section.innerHTML = `<div class="insp-section-title">${escapeHtml(t("inspector.runtime"))}</div>
      <span class="status-pill ${record.status}">${escapeHtml(t(`status.${record.status}`))}</span>
      <span class="muted" style="margin-left:6px">${escapeHtml(duration)}</span>
      ${record.cache_hit ? `<span class="cache-pill">${escapeHtml(t("status.cached"))}</span>` : ""}
      ${record.cache_key ? `<div class="code-note" style="margin-top:5px">${escapeHtml(t("code.key", { key: record.cache_key.slice(0, 16) }))}</div>` : ""}`;
    return section;
  }

  function buildMetrics(metrics) {
    const section = document.createElement("div");
    section.className = "insp-section";
    section.innerHTML = `<div class="insp-section-title">${escapeHtml(t("inspector.metrics"))}</div>`;
    const grid = document.createElement("div");
    grid.className = "metrics";
    for (const [key, value] of Object.entries(metrics)) {
      const k = document.createElement("div");
      k.className = "k";
      k.textContent = key;
      const v = document.createElement("div");
      v.className = "v";
      v.textContent =
        value !== null && typeof value === "object" ? JSON.stringify(value) : String(value);
      grid.append(k, v);
    }
    section.appendChild(grid);
    return section;
  }

  function buildArtifact(artifact, logPath) {
    const box = document.createElement("div");
    box.className = "artifact";
    const size =
      artifact.size_bytes !== undefined
        ? `${(artifact.size_bytes / 1024).toFixed(1)} KB`
        : "";
    box.innerHTML = `<a href="${escapeHtml(artifact.url)}" target="_blank" rel="noopener">
        ${escapeHtml(artifact.label || artifact.port)}
      </a>
      <div class="meta">${escapeHtml(artifact.type || "file")} · ${escapeHtml(
        artifact.path || "",
      )} ${size ? "· " + size : ""}</div>`;
    const isImage = /\.(png|jpe?g|svg)$/i.test(artifact.path || "");
    if (isImage) {
      const img = document.createElement("img");
      img.src = artifact.url;
      img.alt = artifact.label || artifact.port;
      img.loading = "lazy";
      box.appendChild(img);
    }
    if (/\.(tsv|csv|txt)$/i.test(artifact.path || "")) {
      const toggle = document.createElement("button");
      toggle.className = "btn ghost mini";
      toggle.textContent = t("code.previewTable");
      const holder = document.createElement("div");
      holder.className = "table-preview";
      toggle.addEventListener("click", async () => {
        if (holder.dataset.loaded === "1") {
          holder.innerHTML = "";
          holder.dataset.loaded = "";
          toggle.textContent = t("code.previewTable");
          return;
        }
        toggle.disabled = true;
        try {
          const response = await fetch(artifact.url);
          const text = await response.text();
          const lines = text.split(/\r?\n/).filter(Boolean).slice(0, 9);
          const table = document.createElement("table");
          lines.forEach((line, index) => {
            const row = document.createElement("tr");
            for (const cell of line.split("\t")) {
              const tag = index === 0 ? "th" : "td";
              const element = document.createElement(tag);
              element.textContent = cell;
              row.appendChild(element);
            }
            table.appendChild(row);
          });
          holder.appendChild(table);
          holder.dataset.loaded = "1";
          toggle.textContent = t("code.hidePreview");
        } catch (error) {
          holder.textContent = `Preview failed: ${error.message || error}`;
        } finally {
          toggle.disabled = false;
        }
      });
      box.append(toggle, holder);
    }
    if (logPath && state.runId) {
      const logLink = document.createElement("div");
      logLink.className = "meta";
      logLink.innerHTML = `<a href="api/runs/${encodeURIComponent(
        state.runId,
      )}/files/${encodeURIComponent(logPath)}" target="_blank" rel="noopener">${escapeHtml(t("code.openLog"))}</a>`;
      box.appendChild(logLink);
    }
    return box;
  }

  function buildParamField(node, param) {
    const field = document.createElement("div");
    field.className = "field";
    const value = node.params[param.name] ?? param.default ?? "";

    const current = () => node.params[param.name];

    const commit = (next) => {
      node.params[param.name] = next;
      scheduleSave();
    };

    if (param.type === "boolean") {
      field.classList.add("checkbox");
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.checked = Boolean(value);
      input.addEventListener("change", () => commit(input.checked));
      label.append(input, document.createTextNode(param.label));
      field.appendChild(label);
      return field;
    }

    const label = document.createElement("label");
    label.innerHTML = `${escapeHtml(param.label)}${
      param.required ? ' <span class="req">*</span>' : ""
    }`;
    field.appendChild(label);

    let input;
    if (param.type === "enum" && Array.isArray(param.options)) {
      input = document.createElement("select");
      for (const option of param.options) {
        const opt = document.createElement("option");
        opt.value = String(option);
        opt.textContent = String(option);
        if (String(option) === String(value)) opt.selected = true;
        input.appendChild(opt);
      }
      input.addEventListener("change", () => commit(input.value));
    } else if (param.type === "json") {
      input = document.createElement("textarea");
      input.value =
        typeof value === "string" ? value : JSON.stringify(value ?? null, null, 2);
      input.addEventListener("change", () => {
        try {
          commit(JSON.parse(input.value));
        } catch {
          input.classList.add("invalid");
        }
      });
    } else {
      input = document.createElement("input");
      input.type = ["integer", "number"].includes(param.type) ? "number" : "text";
      if (param.type === "integer") input.step = "1";
      if (param.type === "number") input.step = "any";
      input.value = value ?? "";
      input.addEventListener("change", () => {
        if (param.type === "integer") commit(Number.parseInt(input.value, 10));
        else if (param.type === "number") commit(Number.parseFloat(input.value));
        else commit(input.value);
      });
    }
    field.appendChild(input);

    if (param.help) {
      const help = document.createElement("div");
      help.className = "help";
      help.textContent = param.help;
      field.appendChild(help);
    }
    return field;
  }

  function buildEdgeInspector() {
    const edge = state.graph.edges[state.selection.index];
    if (!edge) return document.createElement("div");
    const wrapper = document.createElement("div");
    const source = nodeById(edge.from);
    const target = nodeById(edge.to);
    wrapper.innerHTML = `<div class="insp-title">Connection</div>
      <div class="insp-desc">${escapeHtml(source?.id || edge.from)} · ${escapeHtml(
        edge.from_port,
      )} → ${escapeHtml(target?.id || edge.to)} · ${escapeHtml(edge.to_port)}</div>`;
    const button = document.createElement("button");
    button.className = "btn ghost";
    button.textContent = "Delete connection";
    button.addEventListener("click", deleteSelection);
    wrapper.appendChild(button);
    return wrapper;
  }

  function buildEdgeSection() {
    const section = document.createElement("div");
    section.className = "insp-section";
    if (!state.graph.edges.length) return section;
    section.innerHTML = `<div class="insp-section-title">Connections (${state.graph.edges.length})</div>`;
    const list = document.createElement("div");
    list.className = "edge-list";
    state.graph.edges.forEach((edge, index) => {
      const item = document.createElement("div");
      item.className = "edge-item";
      item.innerHTML = `<span>${escapeHtml(edge.from)}.${escapeHtml(
        edge.from_port,
      )} → ${escapeHtml(edge.to)}.${escapeHtml(edge.to_port)}</span>`;
      const remove = document.createElement("button");
      remove.textContent = "×";
      remove.addEventListener("click", () => {
        state.selection = { kind: "edge", index };
        deleteSelection();
      });
      item.appendChild(remove);
      list.appendChild(item);
    });
    section.appendChild(list);
    return section;
  }

  // ---------------------------------------------------------------- run
  function setRunStatus(status, detail = "") {
    runStatusEl.textContent = detail || status;
    runStatusEl.className = status;
  }

  async function runCanvas() {
    if (!state.graph.nodes.length) {
      window.alert("Add at least one node before running.");
      return;
    }
    runButton.disabled = true;
    setRunStatus("running", "starting…");
    try {
      const response = await fetch("api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ graph: serializeGraph() }),
      });
      const data = await response.json();
      if (!response.ok) {
        const errors = data.errors ? data.errors.join("\n") : data.error;
        window.alert(errors || "Failed to start the run.");
        runButton.disabled = false;
        setRunStatus("failed", "invalid graph");
        return;
      }
      state.runId = data.run_id;
      state.manifest = null;
      pollRun(data.run_id);
    } catch (error) {
      window.alert(`Could not start run: ${error}`);
      runButton.disabled = false;
      setRunStatus("failed", "request failed");
    }
  }

  async function pollRun(runId) {
    clearTimeout(state.pollTimer);
    try {
      const response = await fetch(`api/runs/${encodeURIComponent(runId)}`);
      if (response.ok) {
        state.manifest = await response.json();
        applyManifestStatuses();
        const nodes = Object.values(state.manifest.nodes || {});
        const done = nodes.filter((n) => n.status === "success").length;
        if (state.manifest.status === "running") {
          setRunStatus("running", `running ${done}/${nodes.length}`);
          state.pollTimer = setTimeout(() => pollRun(runId), 1200);
          return;
        }
        runButton.disabled = false;
        setRunStatus(
          state.manifest.status,
          `${state.manifest.status} · ${done}/${nodes.length} ok`,
        );
        renderInspector();
        refreshRuns();
        return;
      }
    } catch {
      /* keep polling; the server may still be writing the manifest */
    }
    state.pollTimer = setTimeout(() => pollRun(runId), 1500);
  }

  // ---------------------------------------------------------------- run history
  async function refreshRuns() {
    try {
      const response = await fetch("api/runs");
      if (!response.ok) return;
      const data = await response.json();
      const current = runsSelect.value;
      runsSelect.innerHTML = '<option value="">Previous runs…</option>';
      for (const run of data.runs || []) {
        const option = document.createElement("option");
        option.value = run.run_id;
        option.textContent = `${run.run_id} · ${run.status}`;
        runsSelect.appendChild(option);
      }
      if (current) runsSelect.value = current;
    } catch {
      /* history is optional */
    }
  }

  async function loadRun(runId) {
    try {
      const response = await fetch(`api/runs/${encodeURIComponent(runId)}`);
      if (!response.ok) throw new Error("run not found");
      const manifest = await response.json();
      if (manifest.graph) loadGraph(manifest.graph);
      state.runId = runId;
      state.manifest = manifest;
      applyManifestStatuses();
      setRunStatus(
        manifest.status || "unknown",
        `${manifest.status || "unknown"} · ${Object.values(manifest.nodes || {}).filter(
          (node) => node.status === "success",
        ).length}/${Object.keys(manifest.nodes || {}).length} ok`,
      );
      renderInspector();
    } catch (error) {
      window.alert(`Could not load run: ${error.message || error}`);
    }
  }

  // ---------------------------------------------------------------- graph io
  function serializeGraph() {
    return {
      name: graphNameInput.value.trim() || "Untitled canvas",
      nodes: state.graph.nodes.map((node) => ({
        id: node.id,
        type: node.type,
        params: node.params,
        x: Math.round(node.x),
        y: Math.round(node.y),
        ...(node.env ? { env: node.env } : {}),
      })),
      edges: state.graph.edges.map((edge) => ({ ...edge })),
    };
  }

  function loadGraph(data, options = {}) {
    if (!data || !Array.isArray(data.nodes)) {
      throw new Error("Invalid canvas JSON: missing 'nodes'.");
    }
    const previousSelection = options.preserveSelection ? state.selection : null;
    const nodes = [];
    for (const raw of data.nodes) {
      const spec = specOf(raw.type);
      if (!spec) continue;
      nodes.push({
        id: String(raw.id || uid(raw.type.replaceAll(".", "_"))),
        type: raw.type,
        params: mergeDefaults(spec, raw.params || {}),
        x: Number(raw.x) || 0,
        y: Number(raw.y) || 0,
        env: raw.env || null,
      });
    }
    const nodeIds = new Set(nodes.map((n) => n.id));
    const edges = (data.edges || [])
      .filter((edge) => nodeIds.has(edge.from) && nodeIds.has(edge.to))
      .map((edge) => ({
        from: edge.from,
        from_port: edge.from_port,
        to: edge.to,
        to_port: edge.to_port,
      }));
    state.graph = {
      name: data.name || "Untitled canvas",
      nodes,
      edges,
    };
    state.selection = previousSelection
      && previousSelection.kind === "node"
      && nodeIds.has(previousSelection.id)
      ? previousSelection
      : null;
    state.manifest = null;
    state.runId = null;
    graphNameInput.value = state.graph.name;
    setRunStatus("idle", "idle");
    renderAll();
    if (options.fit !== false) fitView();
  }

  function scheduleSave() {
    clearTimeout(state.saveTimer);
    state.saveTimer = setTimeout(() => {
      try {
        localStorage.setItem("omics-canvas-graph", JSON.stringify(serializeGraph()));
      } catch {
        /* storage may be unavailable */
      }
      if (state.suppressCanvasSave || !state.canvasId) return;
      clearTimeout(state.canvasSaveTimer);
      state.canvasSaveTimer = setTimeout(saveCanvasNow, 400);
    }, 250);
  }

  function newCanvasId() {
    return `canvas_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
  }

  async function saveCanvasNow() {
    if (state.suppressCanvasSave || !state.canvasId) return;
    try {
      const response = await fetch(`api/canvases/${encodeURIComponent(state.canvasId)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          graph: serializeGraph(),
          base_revision: state.canvasRevision,
          source: "browser",
        }),
      });
      if (response.status === 409) {
        const data = await response.json();
        if (typeof data.revision === "number") state.canvasRevision = data.revision;
        if (data.graph && Array.isArray(data.graph.nodes)) {
          state.suppressCanvasSave = true;
          loadGraph(data.graph, { preserveSelection: true, fit: false });
          state.suppressCanvasSave = false;
          showToast("Canvas updated by the agent.");
        }
        return;
      }
      if (!response.ok) return;
      const data = await response.json();
      if (typeof data.revision === "number") state.canvasRevision = data.revision;
    } catch {
      /* offline: the local graph is still saved */
    }
  }

  async function pollCanvas() {
    if (!state.canvasId || state.suppressCanvasSave) return;
    try {
      const response = await fetch(`api/canvases/${encodeURIComponent(state.canvasId)}`, {
        cache: "no-store",
      });
      if (!response.ok) return;
      const data = await response.json();
      if (!data.graph || !Array.isArray(data.graph.nodes)) return;
      if (typeof data.revision === "number" && data.revision > state.canvasRevision) {
        const unknown = [...new Set(data.graph.nodes.map((node) => node.type))]
          .filter((type) => !state.specMap[type]);
        if (unknown.length) {
          await refreshCatalog();
          if (unknown.some((type) => !state.specMap[type])) return;
        }
        state.canvasRevision = data.revision;
        state.suppressCanvasSave = true;
        loadGraph(data.graph, { preserveSelection: true, fit: false });
        state.suppressCanvasSave = false;
        showToast("Canvas updated by the agent.");
      }
    } catch {
      /* keep the local canvas */
    }
  }

  function startCanvasPoll() {
    if (state.canvasPollTimer) return;
    state.canvasPollTimer = setInterval(pollCanvas, 3000);
  }

  // ---------------------------------------------------------------- custom nodes
  function formatPorts(ports) {
    return (ports || []).map((port) => `${port.id}:${port.type}`).join(", ");
  }

  function parsePorts(text) {
    return String(text || "")
      .split(",")
      .map((chunk) => chunk.trim())
      .filter(Boolean)
      .map((chunk) => {
        const [id, type] = chunk.split(":").map((part) => part.trim());
        return { id, label: id, type: type || "matrix" };
      });
  }

  function formatParams(params) {
    return JSON.stringify(
      (params || []).map((param) => ({
        name: param.name,
        label: param.label,
        type: param.type,
        default: param.default,
        required: Boolean(param.required),
        help: param.help || "",
        ...(param.options ? { options: param.options } : {}),
      })),
      null,
      2,
    );
  }

  function defaultCustomCode(language = "r") {
    if (language === "python") {
      return `def run(task):
    import pandas as pd
    from common import write_table

    outdir = task["outdir"]
    # task["params"] : dict of parameters
    # task["inputs"] : dict of absolute artifact paths
    frame = pd.DataFrame({"value": [1, 2, 3]})
    write_table(frame, outdir + "/python_output.tsv")
    return {
        "ok": True,
        "artifacts": {
            "out": {"file": "python_output.tsv", "type": "table", "label": "Python output"}
        },
        "metrics": {"n": len(frame)},
        "messages": [],
    }
`;
    }
    return `run <- function(task) {
  outdir <- task$outdir
  # task$params : named list of parameters
  # task$inputs : named list of absolute artifact paths
  data <- data.frame(value = 1:3)
  write_tsv_file(data, file.path(outdir, "custom_output.tsv"))
  list(
    ok = TRUE,
    artifacts = list(
      out = list(file = "custom_output.tsv", type = "table", label = "Custom output")
    ),
    metrics = list(n = nrow(data)),
    messages = character()
  )
}
`;
  }

  function field(labelText, value, options = {}) {
    const wrapper = document.createElement("div");
    wrapper.className = "field";
    const label = document.createElement("label");
    label.textContent = labelText;
    wrapper.appendChild(label);
    const input = document.createElement(options.textarea ? "textarea" : "input");
    if (!options.textarea) input.type = "text";
    if (options.code) input.className = "code-input";
    input.value = value ?? "";
    if (options.disabled) input.disabled = true;
    wrapper.appendChild(input);
    if (options.help) {
      const help = document.createElement("div");
      help.className = "hint";
      help.textContent = options.help;
      wrapper.appendChild(help);
    }
    return { wrapper, input };
  }

  function closeModal() {
    el("modal-root").innerHTML = "";
    state.modalOpen = false;
  }

  async function openCustomNodeModal(existing, prefill = {}) {
    if (state.modalOpen) return;
    state.modalOpen = true;
    const initialLanguage = existing?.language || prefill.language || "r";
    let code = prefill.code || defaultCustomCode(initialLanguage);
    if (existing) {
      try {
        const data = await apiJson(`api/nodes/${encodeURIComponent(existing.id)}/code`);
        code = data.code || code;
      } catch {
        /* keep the template */
      }
    }

    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    const modal = document.createElement("div");
    modal.className = "modal";
    modal.innerHTML = `<div class="modal-header"><span>${
      existing ? "Edit custom node" : "New custom node"
    }</span><button type="button" aria-label="Close">×</button></div>`;
    const body = document.createElement("div");
    body.className = "modal-body";
    const footer = document.createElement("div");
    footer.className = "modal-footer";

    const idField = field("Node id", existing?.id || prefill.id || "custom.my_node", {
      disabled: Boolean(existing),
      help: "Must start with 'custom.'. R code lives under r/custom/, Python under py/custom/.",
    });
    const languageField = document.createElement("div");
    languageField.className = "field";
    languageField.innerHTML = "<label>Language</label>";
    const languageSelect = document.createElement("select");
    for (const value of ["r", "python"]) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value === "python" ? "Python" : "R";
      if (value === initialLanguage) option.selected = true;
      languageSelect.appendChild(option);
    }
    if (existing) languageSelect.disabled = true;
    languageField.appendChild(languageSelect);
    const titleField = field("Title", existing?.title || prefill.title || "My custom node");
    const descField = field("Description", existing?.description || prefill.description || "", {
      textarea: true,
    });
    const inputsField = field("Inputs", formatPorts(existing?.inputs || prefill.inputs), {
      help: "Comma-separated ports as id:type (matrix, table, plot). Example: expr:matrix, samples:table",
    });
    const outputsField = field("Outputs", formatPorts(existing?.outputs || prefill.outputs) || "out:table", {
      help: "Each output port must match an artifact key returned by run().",
    });
    const paramsField = field("Parameters (JSON)", formatParams(existing?.params || prefill.params) || "[]", {
      textarea: true,
      help: "Array of {name,label,type,default,required,help,options}.",
    });
    const codeField = field("R code", code, { textarea: true, code: true });

    [idField, { wrapper: languageField }, titleField, descField, inputsField, outputsField, paramsField, codeField].forEach(
      (entry) => body.appendChild(entry.wrapper),
    );
    if (!existing) {
      languageSelect.addEventListener("change", () => {
        const previous = defaultCustomCode(languageSelect.value === "python" ? "r" : "python");
        if (codeField.input.value.trim() === previous.trim() || !codeField.input.value.trim()) {
          codeField.input.value = defaultCustomCode(languageSelect.value);
        }
      });
    }

    const cancel = document.createElement("button");
    cancel.className = "btn ghost";
    cancel.textContent = "Cancel";
    cancel.addEventListener("click", closeModal);
    const save = document.createElement("button");
    save.className = "btn primary";
    save.textContent = existing ? "Save node" : "Create node";
    save.addEventListener("click", async () => {
      save.disabled = true;
      save.textContent = "Saving…";
      try {
        const node = {
          id: idField.input.value.trim(),
          language: languageSelect.value,
          title: titleField.input.value.trim(),
          description: descField.input.value.trim(),
          inputs: parsePorts(inputsField.input.value),
          outputs: parsePorts(outputsField.input.value),
          params: JSON.parse(paramsField.input.value || "[]"),
        };
        await apiJson("api/custom-nodes", {
          method: "POST",
          body: JSON.stringify({ node, code: codeField.input.value }),
        });
        await refreshCatalog();
        if (!existing) {
          const spec = state.specMap[node.id];
          const rect = canvasWrap.getBoundingClientRect();
          const created = {
            id: uid(node.id.replaceAll(".", "_")),
            type: node.id,
            params: expectedDefaults(spec),
            x: Math.round(((rect.width / 2 - state.camera.x) / state.camera.scale - NODE_W / 2) / 8) * 8,
            y: Math.round(((rect.height / 2 - state.camera.y) / state.camera.scale - 40) / 8) * 8,
          };
          state.graph.nodes.push(created);
          state.selection = { kind: "node", id: created.id };
        }
        closeModal();
        renderAll();
        showToast(existing ? "Custom node updated." : "Custom node created.");
      } catch (error) {
        save.disabled = false;
        save.textContent = existing ? "Save node" : "Create node";
        showToast(error.message || String(error), true);
      }
    });
    footer.append(cancel, save);
    modal.append(body, footer);
    backdrop.appendChild(modal);
    backdrop.addEventListener("pointerdown", (event) => {
      if (event.target === backdrop) closeModal();
    });
    modal.querySelector(".modal-header button").addEventListener("click", closeModal);
    el("modal-root").appendChild(backdrop);
  }

  function expectedDefaults(spec) {
    const params = {};
    for (const param of spec?.params || []) {
      if (param.default !== null && param.default !== undefined) {
        params[param.name] = param.default;
      }
    }
    return params;
  }

  // ---------------------------------------------------------------- results drawer
  function openResultsDrawer() {
    const drawer = el("results-drawer");
    if (!drawer.classList.contains("hidden")) {
      drawer.classList.add("hidden");
      return;
    }
    drawer.innerHTML = "";
    const header = document.createElement("div");
    header.className = "drawer-header";
    header.innerHTML = `<span>${escapeHtml(t("results.title"))}</span><button type="button" aria-label="Close">×</button>`;
    header.querySelector("button").addEventListener("click", () => drawer.classList.add("hidden"));
    const body = document.createElement("div");
    body.className = "drawer-body";
    drawer.append(header, body);
    drawer.classList.remove("hidden");

    if (!state.manifest) {
      body.innerHTML = `<div class="muted">${escapeHtml(t("results.empty"))}</div>`;
      return;
    }
    const runId = state.manifest.run_id || state.runId;
    const summary = document.createElement("div");
    summary.className = "run-banner";
    summary.innerHTML = `<b>${escapeHtml(runId)}</b><br/>${escapeHtml(
      state.manifest.status,
    )} · ${state.manifest.total_duration_s ?? 0}s · cache ${
      state.manifest.cache?.hits ?? 0
    } hit / ${state.manifest.cache?.misses ?? 0} miss
      <div class="run-links">
        <a href="api/runs/${encodeURIComponent(runId)}/report" target="_blank" rel="noopener">Report</a>
        <a href="api/runs/${encodeURIComponent(runId)}/export" target="_blank" rel="noopener">Bundle (.zip)</a>
      </div>`;
    body.appendChild(summary);

    const cacheBox = document.createElement("div");
    cacheBox.className = "run-banner";
    cacheBox.innerHTML = `<b>${escapeHtml(t("results.cache"))}</b><br/><span class="cache-stats">Loading…</span>
      <div class="run-links"><a href="#" class="cache-clear">${escapeHtml(t("results.clearCache"))}</a></div>`;
    body.appendChild(cacheBox);
    const cacheStats = cacheBox.querySelector(".cache-stats");
    const loadCache = async () => {
      try {
        const data = await apiJson("api/cache");
        cacheStats.textContent = t("results.cacheStats", { n: data.entries, mb: (data.size_bytes / 1024 / 1024).toFixed(2), dir: data.dir });
      } catch (error) {
        cacheStats.textContent = `Cache unavailable: ${error.message || error}`;
      }
    };
    cacheBox.querySelector(".cache-clear").addEventListener("click", async (event) => {
      event.preventDefault();
      if (!window.confirm(t("results.clearCache") + "?")) return;
      try {
        const data = await apiJson("api/cache", { method: "DELETE" });
        cacheStats.textContent = t("results.cleared", { n: data.before.entries });
      } catch (error) {
        showToast(error.message || String(error), true);
      }
    });
    void loadCache();

    const order = state.manifest.order || Object.keys(state.manifest.nodes || {});
    for (const nodeId of order) {
      const record = state.manifest.nodes?.[nodeId];
      if (!record) continue;
      const artifacts = Object.values(record.artifacts || {});
      if (!artifacts.length) continue;
      const section = document.createElement("div");
      section.className = "result-node";
      section.innerHTML = `<h4>${escapeHtml(record.title || nodeId)} <span class="status-pill ${
        record.status
      }">${escapeHtml(record.status)}</span></h4>`;
      for (const artifact of artifacts) {
        section.appendChild(buildArtifact(artifact, record.log));
      }
      body.appendChild(section);
    }
  }

  // ---------------------------------------------------------------- canvas assistant
  function openChatDrawer(prefill = "") {
    const drawer = el("chat-drawer");
    buildChatDrawer();
    drawer.classList.remove("hidden");
    const textarea = drawer.querySelector(".chat-form textarea");
    if (textarea) {
      if (prefill) {
        textarea.value = prefill;
        textarea.focus();
        textarea.setSelectionRange(textarea.value.length, textarea.value.length);
      } else {
        textarea.focus();
      }
    }
  }

  function toggleChatDrawer() {
    const drawer = el("chat-drawer");
    if (!drawer.classList.contains("hidden")) {
      drawer.classList.add("hidden");
      return;
    }
    openChatDrawer("");
  }

  function selectedNode() {
    if (state.selection?.kind !== "node") return null;
    return state.graph.nodes.find((node) => node.id === state.selection.id) || null;
  }

  function buildNodeAgentPrompt(node) {
    const spec = specOf(node.type);
    const upstream = state.graph.edges
      .filter((edge) => edge.to === node.id)
      .map((edge) => ({ from: edge.from, from_port: edge.from_port, to_port: edge.to_port }));
    const downstream = state.graph.edges
      .filter((edge) => edge.from === node.id)
      .map((edge) => ({ to: edge.to, from_port: edge.from_port, to_port: edge.to_port }));
    const context = {
      canvas_id: state.canvasId,
      selected_node: {
        id: node.id,
        type: node.type,
        title: spec ? spec.title : node.type,
        env: node.env || state.defaultEnv,
        params: node.params,
      },
      upstream,
      downstream,
    };
    return [
      "Edit one node in the open Omics Canvas.",
      "",
      "Canvas context:",
      "```json",
      JSON.stringify(context, null, 2),
      "```",
      "",
      "Workflow:",
      "1. Call omics_canvas_get_canvas to read the full graph.",
      "2. Use omics_canvas_patch_canvas with set_node_params/update_node for parameter or env changes.",
      "3. Use omics_canvas_node_code to read the current implementation and write an override if the change requires code.",
      "4. Validate, run, and report the artifact paths. Keep the node id and its ports unchanged unless the request explicitly asks for a new node.",
      "",
      "Request: ",
    ].join("\n");
  }

  function editSelectedNodeWithAgent() {
    const node = selectedNode();
    if (!node) {
      showToast("Select a node first.", true);
      return;
    }
    state.chatNodeType = node.type;
    openChatDrawer(buildNodeAgentPrompt(node));
  }

  function renderChatMessages(body) {
    body.innerHTML = "";
    for (const message of state.chatMessages) {
      const bubble = document.createElement("div");
      bubble.className = `chat-msg ${message.role}`;
      bubble.textContent = message.text;
      if (message.requestId) bubble.id = `chat-pending-${message.requestId}`;
      body.appendChild(bubble);
    }
    body.scrollTop = body.scrollHeight;
  }

  function updateChatMessage(requestId, patch) {
    const message = state.chatMessages.find((entry) => entry.requestId === requestId);
    if (!message) return;
    Object.assign(message, patch);
    const body = el("chat-drawer").querySelector(".chat-body");
    if (body) renderChatMessages(body);
  }

  function buildChatDrawer() {
    const drawer = el("chat-drawer");
    drawer.innerHTML = "";
    const header = document.createElement("div");
    header.className = "chat-header";
    header.innerHTML = `<span>${escapeHtml(t("chat.title"))}</span><button type="button" aria-label="Close">×</button>`;
    header.querySelector("button").addEventListener("click", () => drawer.classList.add("hidden"));

    const body = document.createElement("div");
    body.className = "chat-body";
    renderChatMessages(body);

    const quick = document.createElement("div");
    quick.className = "chat-quick";
    for (const [labelKey, prompt] of [
      ["chat.quickRna", "Use GSE116271 (foam vs non-foam) to build and run a bulk RNA-seq graph: PCA, volcano, heatmap and GO enrichment. Export the report when done."],
      ["chat.quickProt", "Use PXD046756 (exMM vs BV2) to build and run a bulk proteomics graph: PCA, limma differential abundance, volcano and heatmap. Export the report when done."],
    ]) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = t(labelKey);
      button.addEventListener("click", () => {
        textarea.value = prompt;
        textarea.focus();
      });
      quick.appendChild(button);
    }

    const form = document.createElement("div");
    form.className = "chat-form";
    const textarea = document.createElement("textarea");
    textarea.placeholder = t("chat.placeholder");
    const send = document.createElement("button");
    send.type = "button";
    send.className = "btn primary";
    send.textContent = t("chat.send");
    send.addEventListener("click", () => sendChatMessage(textarea.value));
    textarea.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        sendChatMessage(textarea.value);
      }
    });
    form.append(textarea, send);

    const actions = document.createElement("div");
    actions.className = "chat-actions";
    const open = document.createElement("a");
    open.href = "#";
    open.textContent = t("chat.open");
    open.addEventListener("click", (event) => {
      event.preventDefault();
      if (window.parent === window) {
        showToast(t("chat.unavailable"), true);
        return;
      }
      window.parent.postMessage({ source: "omics-canvas", type: "open-conversation" }, "*");
    });
    actions.appendChild(open);

    const note = document.createElement("div");
    note.className = "chat-note";
    note.textContent = t("chat.note");

    drawer.append(header, body, quick, form, actions, note);
  }

  function sendChatMessage(raw) {
    const text = String(raw || "").trim();
    if (!text) return;
    const textarea = el("chat-drawer").querySelector(".chat-form textarea");
    if (textarea) textarea.value = "";
    state.chatMessages.push({ role: "user", text });
    if (state.selection?.kind === "node") state.chatNodeType = selectedNode()?.type || null;
    if (window.parent === window) {
      state.chatMessages.push({ role: "system", text: t("chat.unavailable") });
      const body = el("chat-drawer").querySelector(".chat-body");
      if (body) renderChatMessages(body);
      return;
    }
    const requestId = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    state.chatMessages.push({
      role: "pending",
      text: t("chat.status"),
      requestId,
    });
    const body = el("chat-drawer").querySelector(".chat-body");
    if (body) renderChatMessages(body);
    window.parent.postMessage({ source: "omics-canvas", type: "prompt", requestId, text }, "*");
    setTimeout(() => {
      const pending = state.chatMessages.find(
        (entry) => entry.requestId === requestId && entry.role === "pending",
      );
      if (pending) {
        updateChatMessage(requestId, {
          role: "error",
          text: t("chat.error", { message: "no response from the host" }),
        });
      }
    }, 20000);
  }

  window.addEventListener("message", (event) => {
    if (event.origin !== window.location.origin) return;
    const data = event.data;
    if (!data || data.source !== "dsh-omics-canvas") return;
    if (data.type === "prompt-ack") {
      updateChatMessage(data.requestId, { role: "system", text: t("chat.sent") });
      if (state.chatNodeType) {
        setTimeout(() => {
          if (state.selection?.kind === "node") renderInspector();
        }, 2000);
        setTimeout(() => {
          if (state.selection?.kind === "node") renderInspector();
        }, 6000);
      }
    } else if (data.type === "prompt-error") {
      updateChatMessage(data.requestId, {
        role: "error",
        text: t("chat.error", { message: data.error || "unknown error" }),
      });
    }
  });

  // ---------------------------------------------------------------- events
  function bindEvents() {
    el("palette-search").addEventListener("input", buildPalette);

    graphNameInput.addEventListener("change", () => {
      state.graph.name = graphNameInput.value.trim() || "Untitled canvas";
      scheduleSave();
    });

    el("btn-run").addEventListener("click", runCanvas);
    el("btn-fit").addEventListener("click", fitView);
    el("btn-new-node").addEventListener("click", () => openCustomNodeModal(null));
    el("btn-chat").addEventListener("click", toggleChatDrawer);
    el("btn-results").addEventListener("click", openResultsDrawer);
    el("btn-refresh-catalog").addEventListener("click", async () => {
      try {
        await refreshCatalog();
        showToast("Node catalog refreshed.");
      } catch (error) {
        showToast(error.message || String(error), true);
      }
    });
    el("btn-toggle-palette").addEventListener("click", () => {
      el("app").classList.toggle("hide-palette");
    });
    el("btn-toggle-inspector").addEventListener("click", () => {
      el("app").classList.toggle("hide-inspector");
    });

    el("btn-new").addEventListener("click", () => {
      if (!window.confirm("Start a new empty canvas?")) return;
      state.graph = { name: "Untitled canvas", nodes: [], edges: [] };
      state.selection = null;
      state.manifest = null;
      state.runId = null;
      state.canvasId = newCanvasId();
      state.canvasRevision = 0;
      localStorage.setItem("omics-canvas-id", state.canvasId);
      graphNameInput.value = state.graph.name;
      setRunStatus("idle", "idle");
      renderAll();
      applyCamera();
      saveCanvasNow();
    });

    el("btn-export").addEventListener("click", () => {
      const data = JSON.stringify(serializeGraph(), null, 2);
      const blob = new Blob([data], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${(state.graph.name || "canvas")
        .replaceAll(/[^a-zA-Z0-9]+/g, "-")
        .toLowerCase()}.canvas.json`;
      link.click();
      URL.revokeObjectURL(url);
    });

    el("btn-import").addEventListener("click", () => el("file-input").click());
    el("file-input").addEventListener("change", async (event) => {
      const file = event.target.files?.[0];
      if (!file) return;
      try {
        const data = JSON.parse(await file.text());
        loadGraph(data);
      } catch (error) {
        window.alert(`Could not import canvas: ${error.message || error}`);
      } finally {
        event.target.value = "";
      }
    });

    runsSelect.addEventListener("change", () => {
      const runId = runsSelect.value;
      if (runId) loadRun(runId);
    });

    exampleSelect.addEventListener("change", async () => {
      const file = exampleSelect.value;
      if (!file) return;
      try {
        const response = await fetch(`api/examples/${encodeURIComponent(file)}`);
        if (!response.ok) throw new Error("Example not found");
        loadGraph(await response.json());
      } catch (error) {
        window.alert(`Could not load example: ${error.message || error}`);
      }
      exampleSelect.value = "";
    });

    // Canvas panning.
    canvasWrap.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      if (event.target.closest(".node")) return;
      if (event.target.closest(".canvas-hud")) return;
      state.drag = {
        kind: "pan",
        startX: event.clientX,
        startY: event.clientY,
        camX: state.camera.x,
        camY: state.camera.y,
      };
      canvasWrap.classList.add("panning");
      clearSelection();
    });

    // Zoom around the pointer.
    canvasWrap.addEventListener(
      "wheel",
      (event) => {
        event.preventDefault();
        const rect = canvasWrap.getBoundingClientRect();
        const mx = event.clientX - rect.left;
        const my = event.clientY - rect.top;
        const worldX = (mx - state.camera.x) / state.camera.scale;
        const worldY = (my - state.camera.y) / state.camera.scale;
        const factor = event.deltaY < 0 ? 1.1 : 0.9;
        const scale = Math.min(2.5, Math.max(0.25, state.camera.scale * factor));
        state.camera.x = mx - worldX * scale;
        state.camera.y = my - worldY * scale;
        state.camera.scale = scale;
        applyCamera();
      },
      { passive: false },
    );

    window.addEventListener("pointermove", (event) => {
      if (state.drag?.kind === "pan") {
        state.camera.x = state.drag.camX + (event.clientX - state.drag.startX);
        state.camera.y = state.drag.camY + (event.clientY - state.drag.startY);
        applyCamera();
        return;
      }
      if (state.drag?.kind === "node") {
        const point = screenToWorld(event.clientX, event.clientY);
        const node = state.drag.node;
        node.x = point.x + state.drag.dx;
        node.y = point.y + state.drag.dy;
        const nodeEl = state.nodeEls.get(node.id);
        if (nodeEl) {
          nodeEl.style.left = `${node.x}px`;
          nodeEl.style.top = `${node.y}px`;
        }
        renderEdges();
        return;
      }
      if (state.connect) {
        state.connect.current = screenToWorld(event.clientX, event.clientY);
        renderEdges();
        const hovered = document.elementFromPoint(event.clientX, event.clientY);
        const dot = hovered?.closest?.(".port-dot.input");
        document
          .querySelectorAll(".port-dot.compatible")
          .forEach((node) => node.classList.remove("compatible"));
        if (dot) dot.classList.add("compatible");
      }
    });

    window.addEventListener("pointerup", (event) => {
      if (state.drag) {
        state.drag = null;
        canvasWrap.classList.remove("panning");
        scheduleSave();
      }
      if (state.connect) {
        const hovered = document.elementFromPoint(event.clientX, event.clientY);
        const dot = hovered?.closest?.(".port-dot.input");
        if (dot) {
          const nodeEl = dot.closest(".node");
          const target = nodeEl ? nodeById(nodeEl.dataset.id) : null;
          if (target) finishConnection(event, target, dot.dataset.port);
        } else {
          state.connect = null;
          renderEdges();
        }
        document
          .querySelectorAll(".port-dot.compatible")
          .forEach((node) => node.classList.remove("compatible"));
      }
    });

    document.addEventListener("keydown", (event) => {
      const tag = event.target.tagName;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(tag)) return;
      if (event.key === "Delete" || event.key === "Backspace") {
        event.preventDefault();
        deleteSelection();
      } else if (event.key === "Escape") {
        state.connect = null;
        renderEdges();
        clearSelection();
      }
    });

    window.addEventListener("resize", () => {
      /* keep the current camera; nothing to recompute */
    });
  }

  // ---------------------------------------------------------------- init
  async function init() {
    try {
      state.catalog = await fetch("api/catalog").then((r) => r.json());
    } catch (error) {
      document.body.innerHTML = `<div style="padding:40px;font-family:sans-serif">
        <h2>Cannot reach the Omics Canvas server</h2>
        <p>Start it with <code>python -m omics_canvas serve</code>.</p>
      </div>`;
      return;
    }
    state.specMap = Object.fromEntries(
      state.catalog.nodes.map((spec) => [spec.id, spec]),
    );
    state.categoryMap = Object.fromEntries(
      state.catalog.categories.map((category) => [category.id, category]),
    );

    buildPalette();
    for (const example of state.catalog.examples || []) {
      const option = document.createElement("option");
      option.value = example.file;
      option.textContent = example.name.replaceAll("-", " ");
      exampleSelect.appendChild(option);
    }

    bindEvents();
    applyCamera();
    refreshRuns();

    state.canvasId = localStorage.getItem("omics-canvas-id") || newCanvasId();
    localStorage.setItem("omics-canvas-id", state.canvasId);
    try {
      const response = await fetch(`api/canvases/${encodeURIComponent(state.canvasId)}`, {
        cache: "no-store",
      });
      if (response.ok) {
        const data = await response.json();
        if (data.graph && Array.isArray(data.graph.nodes) && data.graph.nodes.length > 0) {
          state.canvasRevision = Number(data.revision) || 0;
          loadGraph(data.graph, { preserveSelection: false });
          startCanvasPoll();
          return;
        }
      }
    } catch {
      /* fall back to the local canvas */
    }

    const saved = localStorage.getItem("omics-canvas-graph");
    if (saved) {
      try {
        loadGraph(JSON.parse(saved));
        saveCanvasNow();
        startCanvasPoll();
        return;
      } catch {
        /* fall through to the first example */
      }
    }
    const first = (state.catalog.examples || [])[0];
    if (first) {
      try {
        const response = await fetch(`api/examples/${encodeURIComponent(first.file)}`);
        if (response.ok) {
          loadGraph(await response.json());
          saveCanvasNow();
          startCanvasPoll();
          return;
        }
      } catch {
        /* ignore */
      }
    }
    renderAll();
    saveCanvasNow();
    startCanvasPoll();
  }

  init();
})();
