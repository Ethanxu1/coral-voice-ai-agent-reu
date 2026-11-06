import { useEffect, useState } from 'react'
import { openActionSession, type ActionSession } from '../api/actionSession'
import { resetPose, setHiplessFollow } from '../api/robot'
import { resetRobot } from './robotPose'
import { sleep } from '../utils/sleep'

const RETRY_MS = 2000

/**
 * While mounted, the simulator robot follows the child (the same follow
 * pipeline the main demo uses), arms and head only, in gentle mode. On unmount
 * it stops following and returns to a stand.
 *
 * If the main server isn't up yet (e.g. the page was open before the backend
 * finished starting), it keeps retrying. Returns true once following has started.
 */
export function useRobotFollow(): boolean {
  const [following, setFollowing] = useState(false)

  useEffect(() => {
    let cancelled = false
    let session: ActionSession | null = null
    const run = async () => {
      while (!cancelled) {
        try {
          await resetRobot()
          await sleep(600)
          if (cancelled) return
          await setHiplessFollow(true)
          if (cancelled) return
          session = openActionSession()
          await session.sendText('follow my movement', 'immediate')
          if (!cancelled) setFollowing(true)
          return
        } catch (e) {
          console.warn('start follow failed, retrying', e)
          session?.close()
          session = null
          await sleep(RETRY_MS)
        }
      }
    }
    run()
    return () => {
      cancelled = true
      const s = session
      session = null
      if (s) {
        s.sendText('stop following', 'immediate')
          .catch(() => {})
          .finally(() => {
            s.close()
            resetPose().catch(() => {})
            setHiplessFollow(false)
          })
      } else {
        setHiplessFollow(false)
      }
    }
  }, [])

  return following
}
