"""Simulator fall-state payload contracts."""

from app.api.routes.websocket import _sim_stability_payload


class _Simulator:
    def __init__(self, head_z: float, stabilized: bool = False):
        self.head_z = head_z
        self.stabilized = stabilized

    def get_head_height(self) -> float:
        return self.head_z

    def is_stabilized_preview_active(self) -> bool:
        return self.stabilized


class _Checker:
    fall_threshold_z = 0.25


def test_stability_payload_reports_actual_fall() -> None:
    assert _sim_stability_payload(_Simulator(0.12), _Checker()) == {
        "type": "stability",
        "fallen": True,
        "head_z": 0.12,
        "threshold_z": 0.25,
    }


def test_stability_payload_reports_upright_robot() -> None:
    assert _sim_stability_payload(_Simulator(0.34), _Checker())["fallen"] is False


def test_stability_payload_suppresses_fall_alarm_during_fixed_base_preview() -> None:
    payload = _sim_stability_payload(_Simulator(0.12, stabilized=True), _Checker())

    assert payload["fallen"] is False
    assert payload["stabilized_preview"] is True
