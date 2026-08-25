// Minimal static file server for the built frontend, bound to
// http://localhost:5173 — deliberately NOT a file:// URL, so the origin
// matches the fixed allowlists already baked into vision_server.py and
// speaker_server.py's CORS config. No extra dependency (electron-serve,
// express, etc.) needed for serving a handful of static asset types.
const http = require("http");
const fs = require("fs");
const path = require("path");

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

function start(rootDir, port) {
  server = http.createServer((req, res) => {
    const reqPath = decodeURIComponent(req.url.split("?")[0]);
    let filePath = path.join(rootDir, reqPath);

    // Guard against escaping rootDir via a crafted request path.
    if (!filePath.startsWith(rootDir)) {
      res.writeHead(403);
      res.end();
      return;
    }

    fs.stat(filePath, (err, stat) => {
      if (err || !stat.isFile()) {
        // React Router client-side routes — fall back to index.html.
        filePath = path.join(rootDir, "index.html");
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
