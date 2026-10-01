Let user design conversations and entire pipelines
  - let this pipeline be exportable in two formats
    1. a format that includes stuff like memory and logs in order to modify the model
    2. a format that can be used for immediate running only
  - figure out what is the best format for this, maybe it's like a .md file
    - a simple .md file may or may not be rigid enough in order to define a whole sequence but that can be fine tuned, I'd say start with a single .md file and if that doesn't work then look into other formats like json to add more details
  - have some way of displaying block coding that the agent can modify with. the drag and drop is complementary and high level. main way to modify the block coding is by using voice only


Current goals
  - defining different dimensions that the children can modify like tone, and stuff to work with the physical aspect

Add chat feedback so robot can talk back.


Bugs: 
- server readiness indicator


Activity redesign: give each of the 4 demo activities (Copycat, dance-off, mirror game, animation activity) an honest one-to-one mapping to an AILQ dimension (cognitive/affective/behavioural/ethical), instead of the vague "each activity maps to a learning objective" claim that isn't actually true of how they were designed
  - Copycat -> cognitive: after each round, briefly surface the reasoning stepper (vision -> classification -> decision) so the round teaches how CORAL decided, not just win/loss
  - Dance-off -> ethical: facilitator should explicitly narrate *why* CORAL refuses an unsafe move ("that's not safe, so I won't do it") instead of just saying it "can/cannot do" a move — ties directly to the assessment's obedience/fallibility items
  - Mirror game -> affective: add a debrief question after the game ("what was it like pretending to be the AI trying to copy someone?") so it becomes a perspective-taking/curiosity moment instead of just a capture-speed demo
  - Animation activity -> behavioral self-efficacy: build in a deliberate "oops, this step looks wrong — can you fix it?" moment so the child both commands and corrects a mistake, matching the self-efficacy items
  - context: came out of a 2026-09-29 review of the CORAL Research Paper draft (Activity and Learning Objectives Design section); not yet implemented in the app
