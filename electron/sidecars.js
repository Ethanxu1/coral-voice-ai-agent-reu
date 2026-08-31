// Spawns, health-checks, and tears down the three Python backend sidecars
// (server, vision, speaker) bundled as one PyInstaller onedir binary
// (packaging/backend.spec) dispatched by subcommand. See
// .agents/docs/features/desktop-packaging.md for the full contract.
const { spawn } = require("child_process");
const http = require("http");
const path = require("path");
const fs = require("fs");
const net = require("net");
const ports = require("./ports");

const SIDECARS = [
  { name: "server", arg: "server", port: ports.SERVER },
  { name: "vision", arg: "vision", port: ports.VISION },
  { name: "speaker", arg: "speaker", port: ports.SPEAKER },
];

const STDERR_TAIL_LINES = 40;

let children = [];

function backendExePath() {
  const exeName = process.platform === "win32" ? "backend.exe" : "backend";
  return path.join(process.resourcesPath, "backend", exeName);
}

function isPortInUse(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once("error", (err) => {
      if (err.code === "EADDRINUSE") {
        resolve(true);
      } else {
        resolve(false);
      }
    });
    server.once("listening", () => {
      server.close();
      resolve(false);
    });
    server.listen(port, "127.0.0.1");
  });
}

async function checkPortConflicts() {
  const conflicts = [];
  for (const sidecar of SIDECARS) {
    if (await isPortInUse(sidecar.port)) {
      conflicts.push(sidecar.port);
    }
  }
  if (conflicts.length > 0) {
    return {
      ok: false,
      failed: "server",
      reason: "port-in-use",
      message: `Required port(s) already in use: ${conflicts.join(", ")}. Close the other process and retry.`,
    };
  }
  return { ok: true };
}

function spawnAll(env, logStream) {
  const exePath = backendExePath();
  if (!fs.existsSync(exePath)) {
    throw new Error(`backend binary not found at ${exePath} — build packaging/backend.spec first`);
  }
  children = SIDECARS.map(({ name, arg, port }) => {
    const stderrChunks = [];
    const child = spawn(exePath, [arg], { env });
    child.stdout.on("data", (d) => logStream?.write(`[${name}] ${d}`));
    child.stderr.on("data", (d) => {
      logStream?.write(`[${name}] ${d}`);
      stderrChunks.push(d.toString("utf-8"));
      // Keep a rolling tail of recent stderr for error dialogs.
      while (stderrChunks.join("").split("\n").length > STDERR_TAIL_LINES * 2) {
        stderrChunks.shift();
      }
    });
    return { name, port, child, exitedEarly: false, stderrChunks };
  });
  for (const sidecar of children) {
    sidecar.child.once("exit", (code) => {
      sidecar.exitedEarly = true;
      sidecar.exitCode = code;
    });
  }
  return children;
}

function pingReady(port) {
  return new Promise((resolve) => {
    const req = http.get({ host: "127.0.0.1", port, path: "/ready", timeout: 1000 }, (res) => {
      let body = "";
      res.on("data", (chunk) => (body += chunk));
      res.on("end", () => {
        try {
          const json = JSON.parse(body);
          resolve({ ok: res.statusCode === 200 && json.status === "ok", body: json });
        } catch {
          resolve({ ok: res.statusCode === 200, body: null });
        }
      });
    });
    req.on("error", () => resolve({ ok: false, body: null }));
    req.on("timeout", () => {
      req.destroy();
      resolve({ ok: false, body: null });
    });
  });
}

// Resolves { ok: true } once every sidecar answers /ready with status ok, or
// { ok: false, failed: name, reason: "exited"|"timeout"|"port-in-use", exitCode?, lastLogs? }
// as soon as one is known to have failed.
async function waitHealthy({ timeoutMs = 30000, intervalMs = 500 } = {}) {
  const portCheck = await checkPortConflicts();
  if (!portCheck.ok) return portCheck;

  const deadline = Date.now() + timeoutMs;
  const healthy = new Set();
  while (Date.now() < deadline) {
    for (const sidecar of children) {
      if (sidecar.exitedEarly) {
        return {
          ok: false,
          failed: sidecar.name,
          reason: "exited",
          exitCode: sidecar.exitCode,
          lastLogs: sidecar.stderrChunks.slice(-STDERR_TAIL_LINES).join(""),
        };
      }
      if (!healthy.has(sidecar.name)) {
        const result = await pingReady(sidecar.port);
        if (result.ok) {
          healthy.add(sidecar.name);
        }
      }
    }
    if (healthy.size === children.length) {
      return { ok: true };
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  const failed = children.find((s) => !healthy.has(s.name));
  return {
    ok: false,
    failed: failed?.name,
    reason: "timeout",
    lastLogs: failed?.stderrChunks.slice(-STDERR_TAIL_LINES).join(""),
  };
}

function killAll({ graceMs = 3000 } = {}) {
  for (const { child } of children) {
    if (child.exitCode === null) {
      if (process.platform === "win32") {
        // On Windows a SIGTERM is effectively a kill; use the taskkill tree flag
        // to also take down any grandchildren spawned by the backend binary.
        spawn("taskkill", ["/pid", child.pid, "/t", "/f"]);
      } else {
        child.kill("SIGTERM");
      }
    }
  }
  setTimeout(() => {
    for (const { child } of children) {
      if (child.exitCode === null) {
        if (process.platform === "win32") {
          spawn("taskkill", ["/pid", child.pid, "/t", "/f"]);
        } else {
          child.kill("SIGKILL");
        }
      }
    }
  }, graceMs);
}

module.exports = { spawnAll, waitHealthy, killAll, checkPortConflicts };
