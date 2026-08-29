"""Simple domain model for a saved robot pose."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Pose:
    """A named set of robot joint angles."""

    name: str
    joints: dict[str, float] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
