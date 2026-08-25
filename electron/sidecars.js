// Spawns, health-checks, and tears down the three Python backend sidecars
// (server, vision, speaker) bundled as one PyInstaller onedir binary
// (packaging/backend.spec) dispatched by subcommand. See
// .agents/docs/features/desktop-packaging.md for the full contract.
const { spawn } = require("child_process");
const http = require("http");
const path = require("path");
const fs = require("fs");
const ports = require("./ports");

const SIDECARS = [
  { name: "server", arg: "server", port: ports.SERVER },
  { name: "vision", arg: "vision", port: ports.VISION },
  { name: "speaker", arg: "speaker", port: ports.SPEAKER },
];

let children = [];

function backendExePath() {
  const exeName = process.platform === "win32" ? "backend.exe" : "backend";
  return path.join(process.resourcesPath, "backend", exeName);
}

function spawnAll(env, logStream) {
  const exePath = backendExePath();
  if (!fs.existsSync(exePath)) {
    throw new Error(`backend binary not found at ${exePath} — build packaging/backend.spec first`);
  }
  children = SIDECARS.map(({ name, arg, port }) => {
    const child = spawn(exePath, [arg], { env });
    child.stdout.on("data", (d) => logStream?.write(`[${name}] ${d}`));
    child.stderr.on("data", (d) => logStream?.write(`[${name}] ${d}`));
    return { name, port, child, exitedEarly: false };
  });
  for (const sidecar of children) {
    sidecar.child.once("exit", (code) => {
      sidecar.exitedEarly = true;
      sidecar.exitCode = code;
    });
  }
  return children;
}

function pingHealth(port) {
  return new Promise((resolve) => {
    const req = http.get({ host: "127.0.0.1", port, path: "/health", timeout: 1000 }, (res) => {
      resolve(res.statusCode === 200);
      res.resume();
    });
    req.on("error", () => resolve(false));
    req.on("timeout", () => {
      req.destroy();
      resolve(false);
    });
  });
}

// Resolves { ok: true } once every sidecar answers /health, or
// { ok: false, failed: name, reason: "exited"|"timeout", exitCode? }
// as soon as one is known to have failed.
async function waitHealthy({ timeoutMs = 30000, intervalMs = 500 } = {}) {
  const deadline = Date.now() + timeoutMs;
  const healthy = new Set();
  while (Date.now() < deadline) {
    for (const sidecar of children) {
      if (sidecar.exitedEarly) {
        return { ok: false, failed: sidecar.name, reason: "exited", exitCode: sidecar.exitCode };
      }
      if (!healthy.has(sidecar.name) && (await pingHealth(sidecar.port))) {
        healthy.add(sidecar.name);
      }
    }
    if (healthy.size === children.length) {
      return { ok: true };
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  const failed = children.find((s) => !healthy.has(s.name));
  return { ok: false, failed: failed?.name, reason: "timeout" };
}

function killAll({ graceMs = 3000 } = {}) {
  for (const { child } of children) {
    if (child.exitCode === null) child.kill("SIGTERM");
  }
  setTimeout(() => {
    for (const { child } of children) {
      if (child.exitCode === null) child.kill("SIGKILL");
    }
  }, graceMs);
}

module.exports = { spawnAll, waitHealthy, killAll };
