import { useEffect, useState } from 'react'
import { SERVER_BASE, VISION_BASE } from '../config'
import './ConnectionStatus.css'

interface ServiceStatus {
  name: string
  ok: boolean | null
  url: string
}

const SERVICES: ServiceStatus[] = [
  { name: 'Server', ok: null, url: SERVER_BASE },
  { name: 'Vision', ok: null, url: VISION_BASE },
]

async function checkHealth(url: string): Promise<boolean> {
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

/** Compact all-services indicator for page top bars. */
export function ConnectionHealthDot({ services }: { services: ReturnType<typeof useConnectionStatus> }) {
  const allOk = services.every((s) => s.ok === true)
  const anyDown = services.some((s) => s.ok === false)
  const statusClass = allOk ? 'ok' : anyDown ? 'down' : 'pending'

  return (
    <div className="rd-health-dot" title={`Services: ${services.map((s) => `${s.name} ${s.ok === true ? 'ok' : s.ok === false ? 'down' : '…'}`).join(', ')}`}>
      <span className={`rd-health-dot-ping rd-health-dot-${statusClass}`} />
      <span className="rd-health-dot-label">{allOk ? 'Connected' : anyDown ? 'Reconnecting' : '…'}</span>
    </div>
  )
}
