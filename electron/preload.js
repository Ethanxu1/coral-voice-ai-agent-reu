const { contextBridge, ipcRenderer } = require("electron");

// Exposed only to the onboarding and error windows — the main app window
// loads the built frontend from http://localhost:5173 and never runs this
// preload script (see main.js).
contextBridge.exposeInMainWorld("coral", {
  getConfig: () => ipcRenderer.invoke("config:get"),
  saveConfig: (config) => ipcRenderer.invoke("config:save", config),
  retry: () => ipcRenderer.invoke("app:retry"),
  quit: () => ipcRenderer.invoke("app:quit"),
});
