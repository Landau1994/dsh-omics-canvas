/**
 * dsh-omics-canvas -- browser half.
 *
 * Registers one global sidebar panel ("Omics Canvas") and the matching main
 * panel. The panel is a same-origin iframe served by the host half under
 * `/omics-canvas`, so the existing canvas editor, run API and artifact links
 * work unchanged.
 */

window.__ModuleLoader__.load({
  id: "dsh-omics-canvas",
  factory: (require) => {
    const module = { exports: {} };
    const exports = module.exports;
    Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });

    const React = require("react");
    const PANEL_ID = "omics-canvas";
    let clientCtx = null;

    function postToFrame(frame, payload) {
      try {
        frame?.contentWindow?.postMessage(payload, window.location.origin);
      } catch {
        /* the iframe may be navigating */
      }
    }

    /** Forward a canvas prompt to the active DSH session. */
    async function sendPrompt(text, requestId, frame) {
      try {
        const binding = clientCtx?.uiSession?.adapter?.current?.getSnapshot?.();
        const sessionId = binding?.key;
        if (!sessionId) throw new Error("No active DSH session");
        if (!text || !String(text).trim()) throw new Error("Prompt is empty");
        const reference = clientCtx.sessions.retain(sessionId, { source: "sidebarView" });
        try {
          const result = await reference.binding.session.prompt(
            [{ type: "text", text: String(text) }],
            "queue",
          );
          if (!result || result.ok !== true) {
            throw new Error(result?.error?.message || "The agent rejected the prompt");
          }
        } finally {
          reference.release();
        }
        postToFrame(frame, {
          source: "dsh-omics-canvas",
          type: "prompt-ack",
          requestId,
        });
      } catch (error) {
        postToFrame(frame, {
          source: "dsh-omics-canvas",
          type: "prompt-error",
          requestId,
          error: error instanceof Error ? error.message : String(error),
        });
      }
    }

    /** Small graph glyph: three nodes connected by edges. */
    function CanvasIcon(props) {
      const size = typeof props.size === "number" ? props.size : 20;
      const active = Boolean(props.active);
      return React.createElement(
        "svg",
        {
          width: size,
          height: size,
          viewBox: "0 0 24 24",
          fill: "none",
          stroke: "currentColor",
          strokeWidth: 1.8,
          strokeLinecap: "round",
          strokeLinejoin: "round",
          "aria-hidden": true,
          style: { opacity: active ? 1 : 0.82 },
        },
        React.createElement("circle", { cx: 6, cy: 6, r: 2.2 }),
        React.createElement("circle", { cx: 18, cy: 8, r: 2.2 }),
        React.createElement("circle", { cx: 11, cy: 18, r: 2.2 }),
        React.createElement("path", { d: "M8.1 6.6 15.8 7.6" }),
        React.createElement("path", { d: "M7.2 7.7 10 15.9" }),
        React.createElement("path", { d: "M16.1 9.8 12.6 16.2" }),
      );
    }

    /** Full-height iframe; the canvas owns its own toolbar and state. */
    function CanvasPanel() {
      const frameRef = React.useRef(null);
      React.useEffect(() => {
        const onMessage = (event) => {
          if (event.origin !== window.location.origin) return;
          const frame = frameRef.current;
          if (!frame || event.source !== frame.contentWindow) return;
          const data = event.data;
          if (!data || data.source !== "omics-canvas") return;
          if (data.type === "prompt") {
            void sendPrompt(data.text, data.requestId, frame);
          } else if (data.type === "open-conversation") {
            try {
              clientCtx?.layout?.selectPanel(null);
            } catch {
              /* no conversation panel in this host */
            }
          }
        };
        window.addEventListener("message", onMessage);
        return () => window.removeEventListener("message", onMessage);
      }, []);

      return React.createElement(
        "div",
        {
          style: {
            display: "flex",
            flex: "1 1 auto",
            minHeight: 0,
            height: "100%",
            width: "100%",
            background: "#f8fafc",
          },
        },
        React.createElement("iframe", {
          ref: frameRef,
          src: "/omics-canvas/",
          title: "Omics Canvas",
          style: {
            border: "0",
            display: "block",
            width: "100%",
            height: "100%",
            flex: "1 1 auto",
            background: "#f8fafc",
          },
        }),
      );
    }

    const inject = ["slots", "sessions", "uiSession", "layout"];

    function apply(ctx) {
      clientCtx = ctx;
      ctx.slots.inject("sidebar.panellist", () => ctx.slots.register({
        name: "sidebar.panellist",
        id: PANEL_ID,
        order: 4,
        label: () => "Omics Canvas",
      }, CanvasIcon));

      ctx.slots.inject("main", () => ctx.slots.register({
        name: "main",
        key: PANEL_ID,
      }, CanvasPanel));
    }

    exports.apply = apply;
    exports.inject = inject;
    return module.exports;
  },
});
