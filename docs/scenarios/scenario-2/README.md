# Scenario 2: Fragmented Child-Speech Test Cases

A set of test cases designed to probe how the voice agent handles **realistic child speech** rather than tidy adult instructions. Background and motivation come from the Jun 24 meeting with DK, who asked for 3–5 test cases representing distinct patterns that show up in children's speech with robots — specifically *fragmented* commands where consecutive sentences may have no semantic relationship.

These are companion materials to `scenario-1/`, which exercises the well-formed feedback loop. Scenario 2 is the **robustness suite**: each file isolates one speech pattern and defines a pass/fail criterion the agent can be tested against.

## Why these patterns?

The five patterns below were chosen from the developmental-psychology and child–robot-interaction literature. Each one is a documented behavior in children roughly 3–8 years old — the age range CORAL is targeting.

| File | Pattern | Research basis |
|------|---------|---------------|
| `pattern-1-fragmented-sequential.md` | Short, terse, sequential pose tweaks | DK's Jun 24 example: "raise head up" → "raise chin even higher" → "a little bit lower" |
| `pattern-2-non-sequitur-interruption.md` | Mid-task topic switches and asides | 3-year-olds sustain a single conversational topic only ~20% of the time |
| `pattern-3-self-correction-restart.md` | False starts, mid-utterance revisions | Typical disfluency in ages 2.5–5: revisions, restarts, and interjections without frustration |
| `pattern-4-imaginative-impossible.md` | Pretend-play and impossible asks | Children up to ~8 readily anthropomorphize robots and frame commands inside imaginative scenarios |
| `pattern-5-rapid-fire-overlap.md` | Multiple commands packed close together | Children speak in bursts when excited; commands arrive faster than the agent can complete the previous one |

## How to use these test cases

Each file is a self-contained scenario with:

1. **Pattern description** — what speech behavior is being tested and why it's expected from this user population.
2. **Sample utterances** — actual transcripts as Whisper would produce them, including false starts and run-on phrasing.
3. **Expected router output** — JSON conforming to `src/llm/prompts/router.md`.
4. **Pass criteria** — what the agent needs to do to handle the pattern correctly.
5. **Known failure modes** — how today's pipeline is likely to mishandle it, so regressions are easy to spot.

The router contract has not changed since scenario 1, so the JSON shape, primitive names, angle conventions (degrees, `null` for defaults), and `direction` requirement for bidirectional primitives all still apply.

## Architectural note (per Jun 24 meeting)

The agentic three-model decomposition described in `scenario-1/vision-voice-feedback-loop.md` was set aside in the Jun 24 meeting in favor of a **single-LLM pipeline** on the faster GPT-5.4-mini, with **voice-activated** stable-frame capture rather than continuous frame selection. The test cases below are written for that single-LLM pipeline. Where a pattern would specifically benefit from multi-agent decomposition, the file calls it out as a future consideration.

## Sources

The pattern grounding draws from:

- [Typical vs. Atypical Disfluencies](https://slp.maryville.edu/blog/typical-vs-atypical-disfluencies/) — Maryville University SLP
- [Stuttering in Toddlers & Preschoolers](https://www.healthychildren.org/English/ages-stages/toddler/Pages/Stuttering-in-Toddlers-Preschoolers.aspx) — HealthyChildren.org (AAP)
- [Normal Language Development for Young Children](https://lispeech.com/normal-language-development-young-children/) — Long Island Speech (3-year-old topic-sustain figure)
- [Voice-Controlled Robotics in Early Education](https://www.mdpi.com/2076-3417/14/6/2408) — MDPI Applied Sciences (failure-mode data from a 4–6 year old robot study: ~38% of voice commands required repetition; most failures came from children's inability to formulate the instruction in the available time)
- [Robot speech: how variability matters for child–robot interactions](https://pmc.ncbi.nlm.nih.gov/articles/PMC12832417/) — Frontiers in Robotics and AI
- [The Power of Pretend Play for Children](https://childmind.org/article/the-power-of-pretend-play-for-children/) — Child Mind Institute
