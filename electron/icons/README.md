Drop real app icons here before a public release build:

- `icon.icns` — macOS
- `icon.ico` — Windows
- `icon.png` — Linux (512x512 or larger)

electron-builder auto-detects these from `buildResources: icons`
(`electron-builder.yml`) with no further config. Until they exist, builds
use Electron's default icon.

(Named `icons/`, not electron-builder's default `build/`, because the
repo's root `.gitignore` has a generic `build/` rule from the Python
template that would otherwise swallow this directory.)
