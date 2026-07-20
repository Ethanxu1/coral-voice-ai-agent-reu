"""Locate and load the SMPL neutral model weights.

The SMPL model is gated behind registration at https://smpl.is.tue.mpg.de/. We
cannot bundle the weights, so each developer must place the downloaded file at
``assets/smpl/SMPL_NEUTRAL.pkl`` (or .npz). This module discovers that file and
returns a configured ``smplx`` body model.

Heavy imports (``torch``, ``smplx``) are deferred until ``load_smpl`` runs so
that the rest of the vision pipeline keeps working when the optional SMPL stack
isn't installed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

_REGISTRATION_URL = "https://smpl.is.tue.mpg.de/"
_WEIGHTS_SUBDIR = Path("assets") / "smpl"
# .npz is preferred — the legacy .pkl requires chumpy, which has a broken
# build under Python 3.12.
_PREFERRED_FILENAMES = ("SMPL_NEUTRAL.npz",)


class SMPLWeightsMissingError(RuntimeError):
    """Raised when the SMPL neutral weight file cannot be located."""


def _repo_root() -> Path:
    # src/coral_agent/vision/smpl_loader.py → repo root
    return Path(__file__).resolve().parents[2]


def find_weights() -> Path:
    """Return the path to a discoverable SMPL_NEUTRAL weight file."""
    weights_dir = _repo_root() / _WEIGHTS_SUBDIR
    for name in _PREFERRED_FILENAMES:
        candidate = weights_dir / name
        if candidate.exists():
            return candidate
    raise SMPLWeightsMissingError(
        f"SMPL_NEUTRAL weights not found in {weights_dir}.\n"
        f"  1. Register at {_REGISTRATION_URL} (academic use).\n"
        f"  2. Download the 'SMPL_python_v.1.1.0' archive (or newer).\n"
        f"  3. Place SMPL_NEUTRAL.pkl (or .npz) at {weights_dir}/.\n"
        f"  4. Re-run."
    )


def load_smpl(num_betas: int = 10, device: Optional[str] = None):
    """Return an ``smplx.SMPL`` model loaded onto ``device`` (default: CUDA if available).

    smplx's base ``SMPL`` only loads .pkl directly; for .npz we pre-load the
    arrays and inject them via ``data_struct`` to bypass the pickle path.
    """
    import numpy as np

    import smplx  # type: ignore[import-not-found]
    from smplx.utils import Struct  # type: ignore[import-not-found]
    import torch

    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    weights_path = find_weights()
    npz = np.load(weights_path, allow_pickle=True)
    data_struct = Struct(**{k: npz[k] for k in npz.files})
    model = smplx.SMPL(
        model_path=str(weights_path),
        data_struct=data_struct,
        gender="neutral",
        num_betas=num_betas,
    )
    return model.to(device)
