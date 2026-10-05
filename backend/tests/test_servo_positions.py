"""Reading the real servos' actual positions (GET /positions on the Pi).

Step 3 is blocked on one fact: HOW the real robot's standing ankle gives on
one foot (soft spring vs gear slack vs foot rolling) -- corrections that
help one simulated ankle make another fall. Commanded vs actual servo
position during a held lift answers it. MotionManager has
get_servos_position (seen on the robot 2026-10-03); its argument form is
not known here, so body.py tries the usual ones.
"""

from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path

import pytest

NODES = Path(__file__).resolve().parents[1] / "app" / "robot" / "pi" / "nodes"


class _Resp:
    def __init__(self, success=False, message=""):
        self.success, self.message = success, message


def _body(monkeypatch, get_positions):
    class FakeMotionManager:
        def set_servos_position(self, duration, servos):
            pass

        get_servos_position = get_positions

    fakes = {
        "rospy": types.SimpleNamespace(
            init_node=lambda *a, **k: None, Service=lambda *a, **k: None,
            Subscriber=lambda *a, **k: None, loginfo=lambda *a, **k: None,
            logwarn=lambda *a, **k: None, spin=lambda: None),
        "std_msgs": types.ModuleType("std_msgs"),
        "std_msgs.msg": types.SimpleNamespace(Bool=object, String=object),
        "std_srvs": types.ModuleType("std_srvs"),
        "std_srvs.srv": types.SimpleNamespace(Trigger=object, TriggerResponse=_Resp),
        "ainex_kinematics": types.ModuleType("ainex_kinematics"),
        "ainex_kinematics.motion_manager": types.SimpleNamespace(MotionManager=FakeMotionManager),
        "ainex_demo": types.ModuleType("ainex_demo"),
        "ainex_demo.srv": types.SimpleNamespace(BodyCommand=object, BodyCommandResponse=object),
    }
    for name, mod in fakes.items():
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.syspath_prepend(str(NODES))
    sys.modules.pop("body", None)
    body = importlib.import_module("body")
    return body, body.BodyNode()


@pytest.mark.parametrize("raw,expected", [
    ({1: 480, 2: 510}, {1: 480, 2: 510}),          # dict
    ([[1, 480], [2, 510]], {1: 480, 2: 510}),      # [id, pos] pairs
    ([(1, 480), (2, 510)], {1: 480, 2: 510}),
    ([480, 510], {1: 480, 2: 510}),                # positions in id order
    (None, {}),
])
def test_positions_are_normalised_whatever_shape_the_sdk_returns(monkeypatch, raw, expected):
    body, _ = _body(monkeypatch, lambda self, ids: raw)
    assert body.normalize_positions(raw, [1, 2]) == expected


def test_reads_with_a_list_of_ids(monkeypatch):
    body, node = _body(monkeypatch, lambda self, ids: [[i, 500 + i] for i in ids])
    assert node.read_positions([1, 2]) == {1: 501, 2: 502}


def test_falls_back_to_one_servo_at_a_time(monkeypatch):
    def one(self, sid):
        if isinstance(sid, list):
            raise TypeError("takes an int")
        return 500 + sid

    body, node = _body(monkeypatch, one)
    assert node.read_positions([1, 2]) == {1: 501, 2: 502}


def test_service_reply_is_json_and_reports_failure(monkeypatch):
    body, node = _body(monkeypatch, lambda self, ids: [[i, 500] for i in ids])
    ok = node._handle_positions(None)
    assert ok.success and json.loads(ok.message)["1"] == 500

    def broken(self, *a):
        raise RuntimeError("bus timeout")

    body, node = _body(monkeypatch, broken)
    bad = node._handle_positions(None)
    assert not bad.success and "bus timeout" in bad.message


# ── server.py GET /positions ─────────────────────────────────────────────────


@pytest.fixture
def pi_server(monkeypatch):
    monkeypatch.syspath_prepend(str(NODES))
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    from fastapi.testclient import TestClient

    yield server, TestClient(server.app)
    sys.modules.pop("server", None)


def test_positions_endpoint_returns_what_the_body_read(pi_server, monkeypatch):
    server, client = pi_server
    monkeypatch.setattr(server, "_positions_srv",
                        lambda: _Resp(True, json.dumps({"1": 480, "9": 455})))
    r = client.get("/positions")
    assert r.status_code == 200
    assert r.json() == {"positions": {"1": 480, "9": 455}}


def test_positions_endpoint_reports_a_failed_read(pi_server, monkeypatch):
    server, client = pi_server
    monkeypatch.setattr(server, "_positions_srv", lambda: _Resp(False, "bus timeout"))
    r = client.get("/positions")
    assert r.status_code == 503 and "bus timeout" in r.json()["detail"]


def test_positions_endpoint_without_ros(pi_server, monkeypatch):
    server, client = pi_server
    monkeypatch.setattr(server, "_positions_srv", None)
    assert client.get("/positions").status_code == 503
