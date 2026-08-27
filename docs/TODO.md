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


Bugs to fix
1. I think there is an error with saving poses, it's not saving the final position of the robot at the time that I tell it to save, which means whatever the simulator is in. And also, I think that everything should only be performed in the simulator until the user has saved the pose, or the user wants to demonstrate and tell the robot to perform a pose before it reflects on the physical robot.
