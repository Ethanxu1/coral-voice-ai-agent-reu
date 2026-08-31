import { useEffect, useState } from 'react'
import { getFeaturesBase, getRobotBase } from '../demo/robotConfig'
import { SPEAKER_BASE } from '../demo/config'
import './ConnectionStatus.css'

export interface ServiceStatus {
  name: string
  ok: boolean | null
  url: string
}

export const SERVICES: ServiceStatus[] = [
  { name: 'Server', ok: null, url: getRobotBase() },
  { name: 'Vision', ok: null, url: getFeaturesBase() },
  { name: 'Speaker', ok: null, url: SPEAKER_BASE },
]

export async function checkHealth(url: string): Promise<boolean> {
  try {
    const res = await fetch(`${url}/health`, {
      method: 'GET',
      // A slow/unreachable service should not block the UI for long.
      signal: AbortSignal.timeout(2500),
    })
    return res.ok
  } catch {
    return false
  }
}

export function useConnectionStatus(services = SERVICES) {
  const [statuses, setStatuses] = useState<ServiceStatus[]>(services)

  useEffect(() => {
    let cancelled = false

    const tick = async () => {
      const next = await Promise.all(
        services.map(async (s) => ({
          ...s,
          ok: await checkHealth(s.url),
        }))
      )
      if (!cancelled) setStatuses(next)
    }

    tick()
    const interval = setInterval(tick, 2500)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [services])

  return statuses
}

export default function ConnectionStatus() {
  const services = useConnectionStatus()

  return (
    <div className="cs-root">
      {services.map((s) => (
        <div key={s.name} className="cs-service">
          <span className={`cs-dot cs-dot-${s.ok === null ? 'pending' : s.ok ? 'ok' : 'down'}`} />
          <span className="cs-name">{s.name}</span>
        </div>
      ))}
    </div>
  )
}
