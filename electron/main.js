const { app, BrowserWindow, ipcMain } = require("electron");
const path = require("path");
const fs = require("fs");
const configStore = require("./config-store");
const sidecars = require("./sidecars");
const staticServer = require("./staticServer");
const ports = require("./ports");

let onboardingWindow = null;
let mainWindow = null;
let errorWindow = null;
let logStream = null;

function buildEnv(config) {
  return {
    ...process.env,
    OPENAI_API_KEY: config.openaiApiKey || "",
    LANGFUSE_SECRET_KEY: config.langfuseSecretKey || "",
    LANGFUSE_PUBLIC_KEY: config.langfusePublicKey || "",
    LANGFUSE_BASE_URL: config.langfuseBaseUrl || "https://us.cloud.langfuse.com",
    ROBOT_IP: config.robotIp || "192.168.8.219",
    SPEAKER_PORT: String(ports.SPEAKER),
  };
}

function closeWindow(win) {
  if (win && !win.isDestroyed()) win.close();
}

function showOnboarding(prefill) {
  onboardingWindow = new BrowserWindow({
    width: 420,
    height: 560,
    resizable: false,
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true, nodeIntegration: false },
  });
  onboardingWindow.setMenuBarVisibility(false);
  onboardingWindow.loadFile(path.join(__dirname, "onboarding", "index.html"));
}

function showError({ failed, reason, exitCode, message, lastLogs }) {
  errorWindow = new BrowserWindow({
    width: 520,
    height: 560,
    resizable: true,
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true, nodeIntegration: false },
  });
  errorWindow.setMenuBarVisibility(false);
  const params = new URLSearchParams({
    failed: failed || "",
    reason: reason || "",
    exitCode: exitCode ?? "",
    message: message || "",
    lastLogs: lastLogs || "",
  });
  errorWindow.loadFile(path.join(__dirname, "error.html"), { search: params.toString() });
}

async function showMainWindow() {
  await staticServer.start(path.join(process.resourcesPath, "frontend"), ports.FRONTEND);
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  mainWindow.setMenuBarVisibility(false);
  await mainWindow.loadURL(`http://localhost:${ports.FRONTEND}`);
  mainWindow.show();
}

// Attempts to spawn the three sidecars and bring up the main window. On
// failure, shows error.html instead. Returns nothing — result is reflected
// via window state.
async function launch(config) {
  const logPath = path.join(app.getPath("userData"), "backend.log");
  logStream = fs.createWriteStream(logPath, { flags: "a" });

  sidecars.spawnAll(buildEnv(config), logStream);
  const result = await sidecars.waitHealthy({ timeoutMs: 30000 });
  if (!result.ok) {
    sidecars.killAll();
    return result;
  }
  await showMainWindow();
  return { ok: true };
}

ipcMain.handle("config:get", () => configStore.load());

ipcMain.handle("config:save", async (_event, config) => {
  if (!config.openaiApiKey) {
    return { ok: false, message: "An OpenAI API key is required." };
  }
  configStore.save(config);
  const result = await launch(config);
  if (result.ok) {
    closeWindow(onboardingWindow);
  } else {
    closeWindow(onboardingWindow);
    showError(result);
  }
  return result;
});

ipcMain.handle("app:retry", () => {
  app.relaunch();
  app.exit(0);
});

ipcMain.handle("app:quit", () => app.quit());

app.whenReady().then(async () => {
  const config = configStore.load();
  if (!config.openaiApiKey) {
    showOnboarding(config);
    return;
  }
  const result = await launch(config);
  if (!result.ok) {
    showError(result);
  }
});

app.on("window-all-closed", () => {
  sidecars.killAll();
  staticServer.stop();
  logStream?.end();
  app.quit();
});
