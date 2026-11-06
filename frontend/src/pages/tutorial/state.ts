import { type MapFeaturesResult } from '../../api/vision'

export const ROBOT_NAME = 'CORAL'

export type Screen =
  | 'welcome'
  | 'sim-playground'
  | 'concept-joints'
  | 'concept-intent'
  | 'concept-safety'
  | 'concept-follow'
  | 'concept-save'
  | 'free-practice'
  | 'ready'

export type VoicePhase = 'idle' | 'listening' | 'thinking' | 'done' | 'error'

type CapturePhase = 'idle' | 'countdown' | 'analyzing' | 'result' | 'naming' | 'saved'

export interface StepperState {
  command?: string
  understanding?: string
  safety?: { ok: boolean; reason?: string }
  clarification?: string
  execute?: string
}

export interface State {
  screen: Screen
  // sim playground progress
  blockPart: string | null
  blockDir: string | null
  blockChecking: boolean
  blockConfirmed: boolean
  // voice / stepper state
  voicePhase: VoicePhase
  transcript: string
  error: string
  stepper: StepperState
  // follow / capture
  following: boolean
  captured: MapFeaturesResult | null
  capturePhase: CapturePhase
  countdown: number | null
  savedName: string
  // free practice
  practiceReady: boolean
  // facilitator overlay
  facilitatorOpen: boolean
  sessionLog: string[]
}

export type Action =
  | { type: 'GO'; screen: Screen }
  | { type: 'SET_BLOCK_PART'; val: string | null }
  | { type: 'SET_BLOCK_DIR'; val: string | null }
  | { type: 'BLOCK_CHECKING' }
  | { type: 'BLOCK_CONFIRMED' }
  | { type: 'BLOCK_RESET' }
  | { type: 'SET_VOICE_PHASE'; phase: VoicePhase }
  | { type: 'SET_TRANSCRIPT'; text: string }
  | { type: 'SET_ERROR'; text: string }
  | { type: 'SET_STEPPER'; stepper: StepperState }
  | { type: 'CLEAR_STEPPER' }
  | { type: 'SET_FOLLOWING'; active: boolean }
  | { type: 'SET_CAPTURED'; result: MapFeaturesResult | null }
  | { type: 'SET_CAPTURE_PHASE'; phase: CapturePhase }
  | { type: 'SET_COUNTDOWN'; n: number | null }
  | { type: 'SET_SAVED_NAME'; name: string }
  | { type: 'MARK_PRACTICE_READY' }
  | { type: 'TOGGLE_FACILITATOR' }
  | { type: 'LOG'; text: string }

export const SCREENS: Screen[] = [
  'welcome',
  'sim-playground',
  'concept-joints',
  'concept-intent',
  'concept-safety',
  'concept-follow',
  'concept-save',
  'free-practice',
  'ready',
]

export function reducer(s: State, a: Action): State {
  switch (a.type) {
    case 'GO':
      return {
        ...s,
        screen: a.screen,
        voicePhase: 'idle',
        transcript: '',
        error: '',
        stepper: {},
        countdown: null,
        capturePhase: 'idle',
        // Preserve captured image when flowing follow -> save, otherwise reset is fine.
      }
    case 'SET_BLOCK_PART':
      return { ...s, blockPart: a.val, blockConfirmed: false, blockChecking: false }
    case 'SET_BLOCK_DIR':
      return { ...s, blockDir: a.val, blockConfirmed: false, blockChecking: false }
    case 'BLOCK_CHECKING':
      return { ...s, blockChecking: true, blockConfirmed: false }
    case 'BLOCK_CONFIRMED':
      return { ...s, blockChecking: false, blockConfirmed: true }
    case 'BLOCK_RESET':
      return { ...s, blockPart: null, blockDir: null, blockConfirmed: false, blockChecking: false }
    case 'SET_VOICE_PHASE':
      return { ...s, voicePhase: a.phase }
    case 'SET_TRANSCRIPT':
      return { ...s, transcript: a.text }
    case 'SET_ERROR':
      return { ...s, error: a.text }
    case 'SET_STEPPER':
      return { ...s, stepper: { ...s.stepper, ...a.stepper } }
    case 'CLEAR_STEPPER':
      return { ...s, stepper: {} }
    case 'SET_FOLLOWING':
      return { ...s, following: a.active }
    case 'SET_CAPTURED':
      return { ...s, captured: a.result }
    case 'SET_CAPTURE_PHASE':
      return { ...s, capturePhase: a.phase }
    case 'SET_COUNTDOWN':
      return { ...s, countdown: a.n }
    case 'SET_SAVED_NAME':
      return { ...s, savedName: a.name }
    case 'MARK_PRACTICE_READY':
      return { ...s, practiceReady: true }
    case 'TOGGLE_FACILITATOR':
      return { ...s, facilitatorOpen: !s.facilitatorOpen }
    case 'LOG':
      return { ...s, sessionLog: [...s.sessionLog.slice(-19), a.text] }
    default:
      return s
  }
}

export const initState: State = {
  screen: 'welcome',
  blockPart: null,
  blockDir: null,
  blockChecking: false,
  blockConfirmed: false,
  voicePhase: 'idle',
  transcript: '',
  error: '',
  stepper: {},
  following: false,
  captured: null,
  capturePhase: 'idle',
  countdown: null,
  savedName: '',
  practiceReady: false,
  facilitatorOpen: false,
  sessionLog: [],
}

// ---- Shared visual components ----
