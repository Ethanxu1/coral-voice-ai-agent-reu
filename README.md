## NOTE

This is a deprecated setup meant to be run on the AiNex robot. It uses an ML classifier to identify the pose in the frame.


## Running the Full Pipeline

1. SSH into the Pi and move into Docker.
2. In **four separate terminals**, run one node each:

​```pyrun pose_classifier/publisher.py ```

``` pyrun pose_classifier/head.py ```

``` pyrun pose_classifier/control.py ```

```pyrun pose_classifier/webserver.py```
​

Each process corresponds to a ROS node:

- **publisher.py** — Accesses the AiNex robot's camera, runs the MediaPipe CV model on each frame, and publishes to `/image_annotated`.
- **head.py** — Subscribes to `/image_annotated` and moves the head servos to keep the subject centered.
- **webserver.py** — Serves the web UI, runs the pose-classifier model on the most stable frame, and publishes the result to `/body_commands`.
- **control.py** — Subscribes to `/body_commands` and moves the motors into the corresponding poses.
