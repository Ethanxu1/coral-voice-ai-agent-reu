// Small fetch wrappers: JSON in/out, and errors that carry FastAPI's `detail`.

async function failure(res: Response, what: string): Promise<Error> {
  const body = await res.json().catch(() => null)
  return new Error(`${what} failed: ${res.status} ${body?.detail ?? ''}`.trim())
}

/** POST `body` as JSON; throws on a non-2xx status, returns the parsed reply. */
export async function postJSON<T = unknown>(url: string, body: unknown, what: string): Promise<T> {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw await failure(res, what)
  return res.json().catch(() => null) as Promise<T>
}

/** POST with no body; throws on a non-2xx status. */
export async function post(url: string, what: string): Promise<void> {
  const res = await fetch(url, { method: 'POST' })
  if (!res.ok) throw await failure(res, what)
}

/**
 * Fire-and-forget POST for teardown paths: never throws, and `keepalive` lets
 * the request outlive a page unload.
 */
export async function postBestEffort(url: string, body?: unknown): Promise<void> {
  try {
    await fetch(url, {
      method: 'POST',
      keepalive: true,
      ...(body === undefined
        ? {}
        : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
    })
  } catch {
    /* ignore */
  }
}
