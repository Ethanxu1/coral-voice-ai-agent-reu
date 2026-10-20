import { useReducer, useEffect, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { type ActionResult, type ActionSession, openActionSession } from '../../api/actionSession'
import { VISION_BASE } from '../../config'
import { StageNav, FacilitatorOverlay } from './parts'
import { ConceptFollowScreen } from './screens/ConceptFollowScreen'
import { ConceptIntentScreen } from './screens/ConceptIntentScreen'
import { ConceptJointsScreen } from './screens/ConceptJointsScreen'
import { ConceptSafetyScreen } from './screens/ConceptSafetyScreen'
import { ConceptSaveScreen } from './screens/ConceptSaveScreen'
import { FreePracticeScreen } from './screens/FreePracticeScreen'
import { ReadyScreen } from './screens/ReadyScreen'
import { SimPlaygroundScreen } from './screens/SimPlaygroundScreen'
import { WelcomeScreen } from './screens/WelcomeScreen'
import { type Screen, reducer, initState } from './state'
import './Tutorial.css'

export default function Tutorial() {
  const [s, dispatch] = useReducer(reducer, initState)
  const navigate = useNavigate()
  const actionSessionRef = useRef<ActionSession | null>(null)

  const cameraUrl = VISION_BASE + '/video_feed'

  useEffect(() => {
    actionSessionRef.current = openActionSession('tutorial')
    return () => {
      actionSessionRef.current?.close()
    }
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === '?' && !e.ctrlKey && !e.metaKey && !e.altKey) {
        dispatch({ type: 'TOGGLE_FACILITATOR' })
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const go = useCallback((screen: Screen) => {
    dispatch({ type: 'GO', screen })
  }, [])

  const sendCommand = useCallback(
    async (
      text: string,
      intentType?: 'motion' | 'conversation' | 'immediate' | 'clarification',
      description?: string,
    ): Promise<ActionResult> => {
      return actionSessionRef.current!.sendText(text, intentType, description)
    },
    [],
  )

  const runBlockMove = useCallback(async (part: string, dir: string) => {
    dispatch({ type: 'BLOCK_CHECKING' })
    try {
      await sendCommand(`${dir} the left ${part}`)
      dispatch({ type: 'BLOCK_CONFIRMED' })
    } catch (err) {
      console.error('block move failed', err)
      dispatch({ type: 'SET_ERROR', text: 'That move did not work — try a different one.' })
      dispatch({ type: 'BLOCK_CHECKING' })
    }
  }, [sendCommand])

  const meetRobot = useCallback(() => {
    navigate('/home', { state: { fromApp: true } })
  }, [navigate])

  return (
    <div className="tut-root">
      {/* Facilitator hint */}
      <button
        className="tut-facilitator-hint"
        onClick={() => dispatch({ type: 'TOGGLE_FACILITATOR' })}
        title="Facilitator view (?)"
      >
        ?
      </button>

      {s.screen === 'welcome' && <WelcomeScreen onStart={() => go('sim-playground')} onSkip={() => go('ready')} />}

      {s.screen === 'sim-playground' && (
        <SimPlaygroundScreen
          s={s}
          dispatch={dispatch}
          cameraUrl={cameraUrl}
          onNext={() => go('concept-joints')}
          runBlockMove={runBlockMove}
        />
      )}

      {s.screen === 'concept-joints' && (
        <ConceptJointsScreen
          s={s}
          dispatch={dispatch}
          cameraUrl={cameraUrl}
          onNext={() => go('concept-intent')}
          sendCommand={sendCommand}
        />
      )}

      {s.screen === 'concept-intent' && (
        <ConceptIntentScreen
          s={s}
          dispatch={dispatch}
          cameraUrl={cameraUrl}
          onNext={() => go('concept-safety')}
          sendCommand={sendCommand}
        />
      )}

      {s.screen === 'concept-safety' && (
        <ConceptSafetyScreen
          s={s}
          dispatch={dispatch}
          cameraUrl={cameraUrl}
          onNext={() => go('concept-follow')}
          sendCommand={sendCommand}
        />
      )}

      {s.screen === 'concept-follow' && (
        <ConceptFollowScreen
          s={s}
          dispatch={dispatch}
          cameraUrl={cameraUrl}
          onNext={() => go('concept-save')}
          session={actionSessionRef}
        />
      )}

      {s.screen === 'concept-save' && (
        <ConceptSaveScreen
          s={s}
          dispatch={dispatch}
          cameraUrl={cameraUrl}
          onNext={() => go('free-practice')}
        />
      )}

      {s.screen === 'free-practice' && (
        <FreePracticeScreen
          s={s}
          dispatch={dispatch}
          cameraUrl={cameraUrl}
          onNext={() => go('ready')}
          session={actionSessionRef}
        />
      )}

      {s.screen === 'ready' && <ReadyScreen onMeetRobot={meetRobot} />}

      <StageNav screen={s.screen} onJump={go} />
      <FacilitatorOverlay s={s} dispatch={dispatch} onJump={go} />
    </div>
  )
}
