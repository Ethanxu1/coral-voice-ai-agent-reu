// Getting the child's pose onto the robot, the two ways the Pose Designer
// offers: a camera snapshot, or following the child live and freezing.

import { sendAudioForTranscript } from '../api/actionSession'
import { isSaveCommand } from '../api/poseDesign'
import { getJointPulses, move, setPose } from '../api/robot'
import { mapFeatures } from '../api/vision'
import { captureUtterance } from '../audio/capture'
import { DANCE_POSE_BY_ID } from '../dance/poses'

const STAND = DANCE_POSE_BY_ID.stand.robotPulses
/** Cut an utterance off after this long, so a noise that started it can't hold the pose snapshot back for long. */
const SAVE_UTTERANCE_MAX_MS = 4000

/** The joints a designed pose sets: the arms (the legs stay in the stand, see pose_design.py). */
const ARM_JOINTS = Object.keys(STAND).filter((j) => /_(sho|el)_/.test(j))

/** Only the arm joints of `pulses`. */
export const armsOf = (pulses: Record<string, number>): Record<string, number> =>
  Object.fromEntries(ARM_JOINTS.filter((j) => j in pulses).map((j) => [j, pulses[j]]))

/**
 * The robot's arms as they are now (or as they were in `pulses`), on a clean
 * stand: the full-body pose to design from. The robot is moved there too (the
 * head and legs back to the stand).
 */
export async function poseFromRobot(pulses?: Record<string, number>): Promise<Record<string, number>> {
  const pose = { ...STAND, ...armsOf(pulses ?? (await getJointPulses())) }
  await setPose(pose, { durationMs: 500, waitUntilArrived: true })
  return pose
}

/**
 * Snap the camera and put the robot in the child's pose (behind the server's
 * collision and fall checks). Only the arms are used, so the hips needn't be in
 * frame. Returns what to tell the child if it didn't work.
 */
export async function copyPoseFromCamera(): Promise<string | null> {
  const seen = await mapFeatures({ hipless: true })
  if (!seen.poseDetected) return seen.detail ?? "I couldn't see you. Step back so I can see your arms and hips."
  const { safety } = await move(seen.commands)
  if (safety.fallBlocked) return 'That pose would tip me over! Try a different one.'
  return null
}

/**
 * While CORAL follows the child, listen until they say to keep the pose ("save
 * this pose", "freeze!") and resolve with the robot's pose from the moment they
 * started saying it, so the pose they held is the one kept, not wherever their
 * arms drifted while talking. The mic keeps listening while each utterance is
 * transcribed, so a quick "save it" after other chatter isn't missed. Rejects
 * when the mic fails, or with an AbortError when `signal` aborts (abort it once
 * this resolves, too, to release the mic).
 */
export function waitForSaveCommand(signal: AbortSignal): Promise<Record<string, number>> {
  return new Promise((resolve, reject) => {
    const check = async (blob: Blob, heardAt: Promise<Record<string, number> | null>) => {
      try {
        const text = (await sendAudioForTranscript(blob)).trim()
        if (text && !signal.aborted && (await isSaveCommand(text))) resolve((await heardAt) ?? (await getJointPulses()))
      } catch (e) {
        console.warn('checking for "save this pose" failed', e)
      }
    }
    const listen = async () => {
      while (!signal.aborted) {
        const heardAt: { pulses: Promise<Record<string, number> | null> | null } = { pulses: null }
        const blob = await captureUtterance({
          signal,
          maxMs: SAVE_UTTERANCE_MAX_MS,
          onSpeechStart: () => (heardAt.pulses = getJointPulses().catch(() => null)),
        })
        void check(blob, heardAt.pulses ?? Promise.resolve(null))
      }
    }
    listen().catch(reject)
  })
}
