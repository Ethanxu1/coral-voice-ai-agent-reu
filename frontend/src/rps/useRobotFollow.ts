import { useEffect, useState } from 'react'
import { openActionSession, type ActionSession } from '../api/actionSession'
import { resetPose, setHiplessFollow } from '../api/robot'
import { resetRobot } from './robotPose'
import { sleep } from '../utils/sleep'

const RETRY_MS = 2000

/**
 * Stand the robot up and start it following the child (the same follow
 * pipeline the main demo uses), arms and head only, in gentle mode.
 */
export async function startFollowing(): Promise<ActionSession> {
  await resetRobot()
  await sleep(600)
  await setHiplessFollow(true)
  const session = openActionSession()
  try {
    await session.sendText('follow my movement', 'immediate')
  } catch (e) {
    session.close()
    throw e
  }
  return session
}

/** Stop following. The robot holds the pose it had reached. */
export async function stopFollowing(session: ActionSession): Promise<void> {
  await session.sendText('stop following', 'immediate').catch(() => {})
  session.close()
  setHiplessFollow(false)
}

/**
 * While mounted, the simulator robot follows the child (startFollowing). On
 * unmount it stops following and returns to a stand.
 *
 * If the main server isn't up yet (e.g. the page was open before the backend
 * finished starting), it keeps retrying. Returns true once following has started.
 */
export function useRobotFollow(): boolean {
  const [following, setFollowing] = useState(false)

  useEffect(() => {
    let cancelled = false
    let session: ActionSession | null = null
    const stop = (s: ActionSession) => stopFollowing(s).finally(() => resetPose().catch(() => {}))
    const run = async () => {
      while (!cancelled) {
        try {
          const s = await startFollowing()
          if (cancelled) {
            stop(s)
            return
          }
          session = s
          setFollowing(true)
          return
        } catch (e) {
          console.warn('start follow failed, retrying', e)
          await sleep(RETRY_MS)
        }
      }
    }
    run()
    return () => {
      cancelled = true
      if (session) stop(session)
      else setHiplessFollow(false)
    }
  }, [])

  return following
}
