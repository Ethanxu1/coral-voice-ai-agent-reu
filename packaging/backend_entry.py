"""Single entry point for the PyInstaller-bundled backend.

Dispatches to one of the three existing server `main()` functions based on
argv[1], so the sidecar spawned by Electron is `backend {server|vision|speaker}`
instead of three separately-bundled PyInstaller binaries. See
.agents/docs/features/desktop-packaging.md for why this is one binary.
"""

import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    # Dev-mode convenience: `uv run python packaging/backend_entry.py <cmd>`
    # without needing the project installed first.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

COMMANDS = ("server", "vision", "speaker")


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"usage: backend {{{'|'.join(COMMANDS)}}}", file=sys.stderr)
        sys.exit(1)

    which = sys.argv.pop(1)  # pop so the target main() sees clean argv
    if which == "server":
        import server

        server.main()
    elif which == "vision":
        from vision import vision_server

        vision_server.main()
    elif which == "speaker":
        from speaker import speaker_server

        speaker_server.main()


if __name__ == "__main__":
    main()
