# Voice-to-Motion Success Rate Experiment

**Code version.** This protocol describes the experiment as run at commit `580b1420ce9ac5b173a8db9148f86926b9de443f`, tagged `joint-angle-v1`, on branch `testing/joint-angle-experiment` of https://github.com/Ethanxu1/coral-voice-ai-agent-reu/.

## 1. What this experiment is

**Objective**

Measure how often a spoken refinement command produces the motion the speaker actually asked for. Given a robot already holding a known starting pose, the tester issues a command such as "Raise both arms higher," and the trial is scored on whether the robot performs that action.

This evaluates the command-following path — speech → transcription → LLM → motion primitive → joint targets — not the pose-imitation path measured by the joint-angle experiment.

**Simulator only**

Trials run in the MuJoCo simulator with no physical robot attached. The question is whether the motion planner selects the right motion, which is fully observable in sim; hardware would add servo and mechanical error without informing the outcome being scored. The starting pose is applied through the demo's pose-select button, which drives the sim-only `/set-pose` endpoint.

**Design**

3 starting poses × 5 commands × 3 trials = 45 trials.

Starting poses: Stand, Muscles, Superhero.

Commands (spoken verbatim, identical across all starting poses):

1. "Raise both arms higher"
2. "Bring both arms in"
3. "Rotate both arms counterclockwise about the shoulder a little"
4. "Raise the right arm higher"
5. "Raise the left arm higher"

Every command is a relative refinement — it describes a change from whatever the robot is currently holding, which is why the starting pose is varied rather than fixed.

**Scoring**

Each trial is scored binary, strictly:

* **1** — the robot performed exactly the action stated.
* **0** — anything else. Any deviation from what was said scores zero: the wrong joint, the wrong direction, the wrong arm, extra motion, or no motion at all.

Where the command does not specify a magnitude ("higher," "in," "a little"), the trial is scored on direction only — did the robot move the named joint the way the command indicated. Where it does specify one, the magnitude must also match.

Partial credit is not awarded. A response that moves the right joint the wrong way, or the right way by an implausible amount, scores 0 the same as no response.

**Statistic**
success rate = successful trials / total trials

Reported as a single percentage over all 45 trials. Per-pose and per-command breakdowns follow directly from the trial matrix and are worth reading alongside it.

Reporting is descriptive. One tester, one session, three repetitions per cell — the design supports describing where the pipeline fails, not testing hypotheses about it.

## 2. How to run it

**Setup**

* Start the backend and frontend as described in the main README. No Pi or physical robot is needed; the simulator must be running with the MuJoCo viewer visible so the motion can be observed.
* Open the refined demo page.

**Per-trial procedure**

For each of the 45 trials:

1. Set the starting pose. Use the pose-select button to place the sim robot in the trial's designated starting pose (Stand, Muscles, or Superhero). This applies an authored pose directly to the simulator, bypassing the capture pipeline.
2. Speak the command verbatim as written above.
3. Observe the resulting motion in the simulator.
4. Score 1 or 0 by the rule in §1 — exact action performed, or not.
5. Record any qualitative detail about how it failed: which joint moved, which direction, whether the magnitude qualifier was respected. These notes are the most informative part of the data, since a bare 0 does not distinguish "did nothing" from "did the opposite."
6. Reset. Re-apply the starting pose with the pose-select button, then refresh the browser before the next trial. The refresh clears the demo state machine's conversation history so no trial inherits context from the one before it.

**What gets recorded**

Record data according to the format provided in `~/Voice-to-Motion/Data/7/26/2026`

## 3. Limitations

* Simulator only. No physical robot was used. Results describe the motion planner's command selection and say nothing about whether the chosen motion executes correctly on hardware, where servo range and mechanical limits apply.
* Strict binary scoring discards magnitude information. A response that moves the correct joint in the correct direction by an unreasonable amount scores the same as one that does nothing. This is deliberate — it keeps scoring objective — but it means the success rate cannot distinguish "close but wrong" from "completely wrong," and the qualitative notes are needed to recover that.
* Scoring is a single unblinded judgment. One tester both issues the command and decides whether the result matches it, knowing what was asked. There is no second rater and no agreement statistic. "Exactly the action stated" is applied consistently but is still a human call, particularly for the direction-only cases.
* Direction-only scoring for unspecified magnitudes is generous. "Higher," "in," and "a little" are scored on direction alone, so a technically correct but visually unconvincing motion counts as a success.
* Ambiguous frame of reference in the commands themselves. "Right," "left," and "counterclockwise" are all ambiguous between the speaker's frame and the robot's — the left/right commands were written in quotes for exactly this reason. Some failures may be frame mismatches rather than planning errors, and the design cannot separate the two.
* Five commands, three poses, one tester. The command set is small and hand-picked, and all five are arm commands — no head, torso, or locomotion commands are represented. The success rate is specific to this set and should not be read as a general command-following rate.
* One phrasing per command. Each command was spoken verbatim every time, so the result measures the pipeline's handling of these exact utterances. It does not capture how sensitive the LLM's primitive selection is to rephrasing, which for a system aimed at children is a substantial untested dimension.
* Transcription failures count as failures. A trial where the speech was misheard scores 0 exactly like one where it was heard correctly and planned wrongly. This is intended — the measure is end-to-end, covering everything between the spoken command and the resulting motion. It does mean the success rate is not a measure of the motion planner in isolation, and that a transcription-caused failure and a planning-caused failure are not distinguishable from the score alone.
* Trials are not independent within a cell. Three repetitions of the same command from the same starting pose exercise a largely deterministic path, so they measure LLM sampling variability rather than three independent observations. The browser refresh prevents conversational carryover but does not make the repetitions independent samples of anything else.