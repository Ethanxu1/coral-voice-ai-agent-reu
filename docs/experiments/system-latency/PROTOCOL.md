# Voice-to-Motion Latency Experiment

**Code version.** This protocol describes the experiment as run at commit `580b1420ce9ac5b173a8db9148f86926b9de443f`, tagged `joint-angle-v1`, on branch `testing/joint-angle-experiment` of https://github.com/Ethanxu1/coral-voice-ai-agent-reu/. The measured latency depends on hard-coded delays in the demo state machine, so the reported number is only meaningful against this commit — both delays described below were verified present at it.

## 1. What this experiment is

**Objective**

Measure the wall-clock time from the start of a spoken command to the moment the physical robot begins to move, and separate that total into its known fixed components and a residual attributable to the system.

The measured interval ends at motion onset, not at the completion of the robot's imitation. What this quantifies is how long a child waits between speaking and seeing the robot respond — the responsiveness of the pipeline up to the first movement, not the duration of the movement itself.

**What sits inside the measured interval**

Speaking "Capture my pose" to the robot moving runs through, in order:

1. Speech capture and transcription (Whisper).
2. Intent classification — regex fast path, falling back to the LLM classifier.
3. Robot state set to `DEMO_LOCKED`.
4. A 3-second countdown — three 1-second sleeps in the demo state machine, with the digits displayed as they elapse.
5. Frame capture, MediaPipe pose estimation, torso-frame retargeting, and the self-collision clamp — all inside `/map-features`.
6. An 800 ms fixed UI delay — a hard-coded `sleep(800)` covering the capture flash, which runs before the move is dispatched.
7. Robot state set to `IDLE`, then `/move` dispatched with the fall check.
8. The robot begins to move — the stopwatch stops.

Two of those are deliberate, fixed delays rather than compute: the 3-second countdown and the 800 ms flash. Together they account for 3.8 seconds of the total by design.

**Design**

Seven poses × 3 trials = 21 timed trials: Warrior, T-Pose, Superman, Hands Up, Muscles, Thinker, Dab

The pose determines what the demonstrator holds during the countdown. It does not change the command spoken — every trial uses the same phrase, "Capture my pose" — so the poses vary what the perception and retargeting stages have to handle while the timed path stays identical.

**Apparatus**

* The live demo pipeline, driven by voice through the refined demo page.
* Mac running frontend, LLM server, vision, and TTS; Pi driving the AiNex servos.
* An iPhone stopwatch, operated by hand.

**Statistic**

For each trial the stopwatch gives one number: total elapsed time from the start of the spoken phrase to robot motion onset.

The reported system latency is computed from the session means:

system latency = mean(total elapsed) − mean(time to speak "Capture my pose") − 3 s countdown

The utterance duration is measured separately, as its own average, rather than per trial. The 3-second countdown is subtracted as a known constant.

The 800 ms capture-flash delay is not subtracted and remains inside the reported figure (see Limitations).

Reporting is descriptive — a mean across trials. The design does not support inferential statistics: one speaker, 21 trials, and a single timing instrument.

## 2. How to run it

**Setup**

* Start the full system as described in the main README — backend, frontend, and the Pi's robot server. The robot must be physically powered and reachable, since motion onset is the stop condition.
* Position the speaker so the full body is visible to the camera; the capture stage fails without it, which would void the trial.
* Have the iPhone stopwatch ready in the hand not being used to gesture.

**Per-trial procedure**

For each of the 21 trials:

1. Start the stopwatch at the same instant you begin saying "Capture my pose." The button press and the first syllable should coincide as closely as possible.
2. Speak the phrase at a regular, unhurried cadence. Consistency matters here more than speed, because a single average utterance duration is subtracted from every trial — an unusually fast or slow delivery pushes that trial's residual in the opposite direction.
3. Hold the pose through the countdown so the capture succeeds.
4. Stop the stopwatch the moment the physical robot begins to move — first visible servo motion, not the completion of the pose.
5. Record the raw elapsed time exactly as the stopwatch reads it. Do not subtract anything during the session; the countdown and utterance time come off during analysis.
6. If the capture fails (pose not detected) or the fall check blocks the move, the robot never moves and there is nothing to stop on. Discard and re-run that trial.

**Measuring the utterance duration**

Separately from the timed trials, record the time to say "Capture my pose" aloud at the same cadence, several times, and take the mean. This value is subtracted from every trial, so it should be measured under the same conditions as the trials themselves and reported alongside the result.

**What gets recorded**

This experiment has no tester mode and writes no files automatically — recording is manual.

Record the data as seen in this Drive under `~/System Latency/Data/7/27/2026`

## 3. Limitations

* Manual timing on both ends. Start and stop are human-triggered, so each trial carries the operator's reaction time twice — typically a couple hundred milliseconds each, and not necessarily cancelling, since starting on your own speech and stopping on a visual cue are different reaction tasks. This is the dominant source of measurement noise and it is not quantified here.
* Motion onset is judged by eye. "The robot begins to move" is a visual judgment, and small initial servo movements may be noticed late. This biases readings upward.
* A single averaged utterance duration is subtracted from every trial. Per-trial speech duration is not measured, so any trial-to-trial variation in delivery is pushed into that trial's residual rather than removed from it. The unhurried-cadence instruction limits this but does not eliminate it.
* 3.8 s of the interval is fixed delay, not computation. The 3-second countdown is subtracted; the 800 ms capture flash is not. The reported system latency therefore contains a hard-coded delay, and the compute-bound portion of the pipeline is smaller than the figure suggests.
* The countdown is a constant only for this code path. The 3 seconds comes from three 1-second sleeps in the refined demo's state machine. Other paths in the codebase gate the countdown on text-to-speech completion instead, where the elapsed time is not exactly 3 seconds. The subtraction is valid only for the demo path described here.
* No per-stage instrumentation. A stopwatch yields one number per trial, so the decomposition is limited to subtracting components whose duration is known in advance. Transcription, intent classification, MediaPipe, retargeting, and network round-trips to the Pi are not separable from one another in this data — they are only visible in aggregate as the residual.
* Intent classification is not a fixed cost. "Capture my pose" matches the regex fast path, which resolves without an LLM call. A phrasing that fell through to the LLM classifier would add substantially more latency, so this result characterizes the fast path, not voice commands generally.
* Network and load conditions are uncontrolled. Transcription depends on an external API, and the Mac→Pi hop depends on local network conditions. Neither was held constant or recorded per trial.
* One speaker, one session. All trials come from a single person's voice and delivery, so the result carries no estimate of how latency varies across speakers — a child's voice, in particular, is the actual target condition and is not represented.
* Failed trials are re-run rather than recorded. Captures that fail and moves the fall check blocks produce no stop event and are repeated. The reported latency is therefore conditional on the pipeline succeeding, and excludes the (longer) experience of a child whose first attempt does not work.