// Fixed ports matching the backend's hardcoded values and the frontend's
// hardcoded localhost URLs (frontend/src/demo/robotConfig.ts, config.ts, and
// several scattered literals — see .agents/docs/features/desktop-packaging.md).
// These are not meant to be reconfigured: changing one here without also
// updating the frontend call sites will break the packaged app.
module.exports = {
  SERVER: 8000,
  VISION: 8001,
  SPEAKER: 5002,
  FRONTEND: 5173,
};
