"""PyInstaller hook for the `glfw` package.

`glfw` ships its native library under session-specific subdirectories
(`glfw/x11/libglfw.so`, `glfw/wayland/libglfw.so` on Linux; similar on
other platforms) and loads it via its own runtime search logic in
`glfw/__init__.py`, not a standard import — invisible to PyInstaller's
static analysis, so it's silently dropped without this hook. Required
for `mujoco.viewer` (imported by src/simulator/mujoco_sim.py), which
imports `glfw` at module load time even when the viewer is never opened.
"""

from PyInstaller.utils.hooks import collect_dynamic_libs

binaries = collect_dynamic_libs("glfw")
