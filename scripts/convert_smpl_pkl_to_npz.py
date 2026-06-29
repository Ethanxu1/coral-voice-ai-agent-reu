"""Convert a legacy SMPL_NEUTRAL .pkl into a Python-3.12-friendly .npz.

The official SMPL release ships ``basicmodel_neutral_lbs_10_207_0_v1.1.0.pkl``,
which stores its arrays as ``chumpy.Ch`` objects. ``chumpy`` doesn't build on
Python 3.12, so we stub it out at unpickle time and re-save as a clean .npz.

Usage:
    python scripts/convert_smpl_pkl_to_npz.py \\
        path/to/basicmodel_neutral_lbs_10_207_0_v1.1.0.pkl \\
        assets/smpl/SMPL_NEUTRAL.npz
"""

from __future__ import annotations

import pickle
import sys
import types
from pathlib import Path

import numpy as np


class _FakeCh:
    """Stand-in for chumpy.Ch — captures the underlying value via __setstate__.

    chumpy.Ch stores its array under the ``x`` attribute. We don't subclass
    ndarray here because pickle's reconstructor calls ``object.__new__(cls)``,
    which numpy refuses for ndarray subclasses.
    """

    def __setstate__(self, state):
        if isinstance(state, dict) and "x" in state:
            self._array = np.asarray(state["x"])
        elif isinstance(state, np.ndarray):
            self._array = state
        else:
            self._array = np.asarray(state) if state is not None else None

    def __reduce__(self):
        return (self.__class__, (), self.__dict__)


def _install_chumpy_stub() -> None:
    chumpy_mod = types.ModuleType("chumpy")
    chumpy_mod.Ch = _FakeCh  # type: ignore[attr-defined]
    sys.modules["chumpy"] = chumpy_mod
    sys.modules["chumpy.ch"] = chumpy_mod


def _unwrap(v):
    """Recursively replace _FakeCh wrappers and densify scipy sparse matrices."""
    if isinstance(v, _FakeCh):
        return v._array
    if "scipy.sparse" in str(type(v)):
        return np.asarray(v.todense())
    if isinstance(v, dict):
        return {k: _unwrap(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return type(v)(_unwrap(x) for x in v)
    return v


def convert(src: Path, dst: Path) -> None:
    _install_chumpy_stub()
    with src.open("rb") as f:
        data = pickle.load(f, encoding="latin1")

    cleaned: dict[str, np.ndarray] = {}
    for k, v in data.items():
        v = _unwrap(v)
        if v is None:
            continue
        try:
            cleaned[k] = np.asarray(v)
        except Exception:
            # Skip non-array entries (e.g., callable lambdas in some packs).
            pass

    dst.parent.mkdir(parents=True, exist_ok=True)
    np.savez(dst, **cleaned)
    print(f"Wrote {dst} ({len(cleaned)} arrays)")


def main() -> None:
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    if not src.exists():
        print(f"error: source file not found: {src}", file=sys.stderr)
        sys.exit(1)
    convert(src, dst)


if __name__ == "__main__":
    main()
