// Minimal static file server for the built frontend, bound to
// http://localhost:5173 — deliberately NOT a file:// URL, so the origin
// matches the fixed allowlists already baked into vision_server.py and
// speaker_server.py's CORS config. No extra dependency (electron-serve,
// express, etc.) needed for serving a handful of static asset types.
const http = require("http");
const fs = require("fs");
const path = require("path");
const ports = require("./ports");

const MIME_TYPES = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".ico": "image/x-icon",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
};

let server = null;

function runtimeConfigScript() {
  // Injected into index.html so the packaged frontend knows where the local
  // sidecars are, even if the Vite build-time env variables are not set.
  const runtime = {
    ROBOT_BASE: `http://127.0.0.1:${ports.SERVER}`,
    FEATURES_BASE: `http://127.0.0.1:${ports.VISION}`,
    ROBOT_STREAM: `http://127.0.0.1:${ports.VISION}`,
    SPEAKER_BASE: `http://127.0.0.1:${ports.SPEAKER}`,
    ACTION_WS: `ws://127.0.0.1:${ports.SERVER}/ws`,
    SIM_WS: `ws://127.0.0.1:${ports.SERVER}/ws/sim`,
  };
  return `<script>window.__CORAL_RUNTIME__ = ${JSON.stringify(runtime)};</script>`;
}

function start(rootDir, port) {
  const indexPath = path.join(rootDir, "index.html");
  let indexHtml = null;
  try {
    indexHtml = fs.readFileSync(indexPath, "utf-8");
    // Inject runtime config just before the first <script> or <head> close.
    const injectionPoint = indexHtml.search(/<script/i);
    if (injectionPoint >= 0) {
      indexHtml = indexHtml.slice(0, injectionPoint) + runtimeConfigScript() + indexHtml.slice(injectionPoint);
    } else {
      indexHtml = indexHtml.replace("</head>", runtimeConfigScript() + "</head>");
    }
  } catch (err) {
    console.error("Failed to read/index.html for injection:", err);
  }

  server = http.createServer((req, res) => {
    const reqPath = decodeURIComponent(req.url.split("?")[0]);
    let filePath = path.join(rootDir, reqPath);

    // Guard against escaping rootDir via a crafted request path.
    if (!filePath.startsWith(rootDir)) {
      res.writeHead(403);
      res.end();
      return;
    }

    // Serve the injected index.html for the root and for any client-side route.
    if (reqPath === "/" || reqPath === "/index.html") {
      if (indexHtml) {
        res.writeHead(200, { "Content-Type": "text/html" });
        res.end(indexHtml);
        return;
      }
    }

    fs.stat(filePath, (err, stat) => {
      if (err || !stat.isFile()) {
        // React Router client-side routes — fall back to index.html.
        if (indexHtml) {
          res.writeHead(200, { "Content-Type": "text/html" });
          res.end(indexHtml);
        } else {
          res.writeHead(404);
          res.end("not found");
        }
        return;
      }
      fs.readFile(filePath, (readErr, data) => {
        if (readErr) {
          res.writeHead(404);
          res.end("not found");
          return;
        }
        const ext = path.extname(filePath);
        res.writeHead(200, { "Content-Type": MIME_TYPES[ext] || "application/octet-stream" });
        res.end(data);
      });
    });
  });
  return new Promise((resolve) => server.listen(port, "127.0.0.1", resolve));
}

function stop() {
  return new Promise((resolve) => (server ? server.close(() => resolve()) : resolve()));
}

module.exports = { start, stop };
