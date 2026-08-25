const form = document.getElementById("setup-form");
const submitBtn = document.getElementById("submit");
const errorEl = document.getElementById("error");

window.coral.getConfig().then((config) => {
  if (config?.robotIp) document.getElementById("robotIp").value = config.robotIp;
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  errorEl.hidden = true;
  submitBtn.disabled = true;
  submitBtn.textContent = "Starting…";

  const config = {
    openaiApiKey: document.getElementById("openaiApiKey").value.trim(),
    langfuseSecretKey: document.getElementById("langfuseSecretKey").value.trim(),
    langfusePublicKey: document.getElementById("langfusePublicKey").value.trim(),
    robotIp: document.getElementById("robotIp").value.trim(),
  };

  const result = await window.coral.saveConfig(config);
  if (!result.ok) {
    errorEl.textContent = result.message || "Could not start CORAL. Please check your API key and try again.";
    errorEl.hidden = false;
    submitBtn.disabled = false;
    submitBtn.textContent = "Start CORAL";
  }
  // On success, main.js closes this window and shows the main app window.
});
