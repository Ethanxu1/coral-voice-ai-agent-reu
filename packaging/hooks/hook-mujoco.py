"""PyInstaller hook for `mujoco`.

MuJoCo loads mesh-format decoders (e.g. `mujoco/plugin/libstl_decoder.so`)
as runtime plugins, not via a normal import or ELF dependency — invisible
to PyInstaller's static analysis, so they're silently dropped without this
hook. Without it, `mujoco.MjModel.from_xml_path()` raises "no decoder found
for mesh file ...STL" for any model that references mesh geometry (as the
AiNex model does — see assets/ainex/ainex.xml).
"""

from PyInstaller.utils.hooks import collect_dynamic_libs

binaries = collect_dynamic_libs("mujoco")
