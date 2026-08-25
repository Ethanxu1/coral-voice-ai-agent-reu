"""PyInstaller hook for `mediapipe`.

mediapipe's C bindings (mediapipe/tasks/python/core/mediapipe_c_bindings.py)
load `libmediapipe.{so,dylib,dll}` via `importlib.resources.files(
"mediapipe.tasks.c")` + `ctypes.CDLL(absolute_path)` — a package-data lookup
PyInstaller's static analysis can't see, since nothing does a plain `import
mediapipe.tasks.c`. Without this hook the module and its native library are
silently dropped, and pose/face landmark loading fails at runtime (in a
background thread, so it doesn't even surface as a startup crash — see
.agents/docs/features/desktop-packaging.md) with `ModuleNotFoundError: No
module named 'mediapipe.tasks.c'`.

collect_dynamic_libs (not collect_data_files, which silently drops .so
files by default and returned an empty list here) preserves the
package-relative destination (verified: `mediapipe/tasks/c`, not the
bundle's top-level binary dir) — required since the library is resolved
via importlib.resources at that exact package-relative path, not found
via dlopen/ctypes.util search.
"""

from PyInstaller.utils.hooks import collect_dynamic_libs

hiddenimports = ["mediapipe.tasks.c"]
binaries = collect_dynamic_libs("mediapipe.tasks.c")
