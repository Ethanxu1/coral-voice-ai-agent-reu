import { useEffect } from 'react'
import {
  setAngleArcsEnabled,
  setFallCheckEnabled,
  setMujocoViewerOnLaunch,
} from '../demo/api'
import { useRobotConfig } from '../demo/robotConfig'

// Some robotConfig settings are only remembered by the browser (localStorage) —
// the flags they control live in the server processes' memory, not on disk. A
// fresh page load or a server restart therefore leaves the servers on their own
// env defaults while the UI still shows the remembered value.
//
// Mount this once at the app root so the remembered settings are pushed on every
// page load, whatever route the user lands on. It used to live in
// RobotModeToggle, which renders only on "/" — open the refined demo directly
// and the fall check stayed on (its ENABLE_FALL_CHECK default) even though the
// toggle read "Off", so adjustments were silently blocked as unstable.
//
// Every setter here is best-effort and swallows its own errors, so a server
// that isn't up yet costs nothing.
export function useServerSettingsSync(): void {
  const { showAngleArcs, fallCheckEnabled, mujocoViewerOnLaunch } = useRobotConfig()

  // One effect per setting so a change only re-pushes the flag that changed.
  useEffect(() => {
    setAngleArcsEnabled(showAngleArcs)
  }, [showAngleArcs])
  useEffect(() => {
    setFallCheckEnabled(fallCheckEnabled)
  }, [fallCheckEnabled])
  // The server only reads this one at startup — pushing it on every load is what
  // makes the toggle's remembered state the one used next launch.
  useEffect(() => {
    setMujocoViewerOnLaunch(mujocoViewerOnLaunch)
  }, [mujocoViewerOnLaunch])
}
