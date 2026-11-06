import { useEffect } from 'react'
import { setSimUpright } from '../api/robot'

/**
 * Pin the simulated robot upright while the calling page (a test page) is open
 * and `pinned` is true. Each change sends exactly one request; the pin is
 * released when the page unmounts or the tab is closed. Re-pinning also
 * stands a fallen robot up.
 */
export function useSimUpright(pinned: boolean): void {
  useEffect(() => {
    setSimUpright(pinned)
  }, [pinned])

  useEffect(() => {
    const release = () => { setSimUpright(false) }
    window.addEventListener('pagehide', release)
    return () => {
      window.removeEventListener('pagehide', release)
      release()
    }
  }, [])
}
