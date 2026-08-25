// Plain-JSON config persistence under Electron's userData directory. Not an
// OS keychain (keytar) — deliberately kept simple to avoid a native-module
// build dependency in the cross-platform CI matrix. See
// .agents/docs/features/desktop-packaging.md, "Known limitations".
const fs = require("fs");
const path = require("path");
const { app } = require("electron");

function configPath() {
  return path.join(app.getPath("userData"), "coral-config.json");
}

function load() {
  try {
    return JSON.parse(fs.readFileSync(configPath(), "utf-8"));
  } catch {
    return {};
  }
}

function save(config) {
  fs.mkdirSync(path.dirname(configPath()), { recursive: true });
  fs.writeFileSync(configPath(), JSON.stringify(config, null, 2), "utf-8");
}

module.exports = { load, save };
