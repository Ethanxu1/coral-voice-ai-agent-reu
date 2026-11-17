"""Tests for the system-intent matcher in app.services.intent."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.intent import (
    SavePoseDialog,
    _SaveStage,
    classify_system_intent,
    handle_save_dialog,
    try_handle_system_intent,
)
from app.state import state


class FakeWebSocket:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


@pytest.fixture
def websocket():
    return FakeWebSocket()


@pytest.fixture
def save_dialog():
    return SavePoseDialog()


@pytest.fixture
def memory():
    from app.services.chat import HierarchicalMemory

    return HierarchicalMemory()


class TestClassifySystemIntent:
    def test_follow_start_phrases(self):
        for phrase in ["follow me", "mirror my movements", "copy my moves"]:
            assert classify_system_intent(phrase) == "follow_start", phrase

    def test_follow_stop_does_not_require_active_follow(self):
        # Even if the backend thinks follow is not active, "stop following" must
        # still classify as a stop command so it is not reinterpreted as motion.
        assert classify_system_intent("stop following") == "follow_stop"
        assert classify_system_intent("stop following my movement") == "follow_stop"
        assert classify_system_intent("stop mirroring") == "follow_stop"

    def test_capture_phrases(self):
        for phrase in ["capture my pose", "take a picture", "copy my pose"]:
            assert classify_system_intent(phrase) == "capture_pose", phrase

    def test_save_phrases(self):
        for phrase in ["save this pose", "remember this", "keep this pose"]:
            assert classify_system_intent(phrase) == "save_current_pose", phrase

    def test_play_pose_phrases(self):
        for phrase in [
            "play my right arm up pose",
            "perform the superhero pose",
            "do the pose I saved",
        ]:
            assert classify_system_intent(phrase) == "play_pose", phrase

    def test_unmatched_falls_through(self):
        assert classify_system_intent("hello") is None
        assert classify_system_intent("what's your name") is None


@pytest.fixture
def anyio_backend():
    return "asyncio"


class TestTryHandleSystemIntent:
    @pytest.mark.anyio
    @patch("app.services.tts.generate_speech", return_value=b"fake-mp3-bytes")
    @patch("app.services.intent.list_pose_names", return_value=["Right arm up", "superhero"])
    @patch("app.services.intent.get_pose", return_value={"l_sho_pitch": 1.0})
    @patch("app.services.intent._execute_on_hardware_if_connected", new_callable=AsyncMock)
    async def test_play_pose_fuzzy_match_and_memory_log(
        self, mock_exec, mock_get_pose, mock_list, mock_speech, websocket, save_dialog, memory
    ):
        handled = await try_handle_system_intent(
            "can you perform right arm up?",
            websocket,
            save_dialog,
            memory=memory,
        )
        assert handled is True
        mock_exec.assert_awaited_once_with({"l_sho_pitch": 1.0})
        # A spoken system-intent reply must be followed by TTS audio, same as
        # a regular chat_response — not just silently sent as text.
        assert len(websocket.sent) == 2
        assert "Playing your saved pose: Right arm up" in websocket.sent[0]["content"]
        assert websocket.sent[1]["type"] == "audio_response"
        assert websocket.sent[1]["audio_base64"]
        # Memory should record the user request and assistant response.
        assert len(memory.short_term) == 2
        assert memory.short_term[0]["role"] == "user"
        assert "perform right arm up" in memory.short_term[0]["content"].lower()
        assert memory.short_term[1]["role"] == "assistant"

    @pytest.mark.anyio
    @patch("app.services.intent.list_pose_names", return_value=[])
    async def test_play_pose_no_saved_poses_lists_help(self, mock_list, websocket, save_dialog, memory):
        handled = await try_handle_system_intent(
            "play my pose",
            websocket,
            save_dialog,
            memory=memory,
        )
        assert handled is True
        assert "don't have any saved poses" in websocket.sent[0]["content"]
        assert len(memory.short_term) == 2

    @pytest.mark.anyio
    @patch("app.services.intent.list_pose_names", return_value=["Left arm up", "Right arm up"])
    async def test_library_lists_poses_and_logs_memory(
        self, mock_list, websocket, save_dialog, memory
    ):
        handled = await try_handle_system_intent(
            "what are my poses",
            websocket,
            save_dialog,
            memory=memory,
            intent_override="library",
        )
        assert handled is True
        content = websocket.sent[0]["content"]
        assert "2 saved poses" in content
        assert "Left arm up" in content
        assert "Right arm up" in content
        assert len(memory.short_term) == 2
        assert memory.short_term[0]["content"] == "what are my poses"

    @pytest.mark.anyio
    async def test_save_current_pose_logs_memory(self, websocket, save_dialog, memory):
        with patch("app.services.intent._get_robot_state", return_value={"l_sho_pitch": 0.5}):
            handled = await try_handle_system_intent(
                "save this pose",
                websocket,
                save_dialog,
                memory=memory,
            )
        assert handled is True
        assert save_dialog.stage.value == "awaiting_confirm"
        assert len(memory.short_term) == 2
        assert "save this pose" in memory.short_term[0]["content"]
        assert memory.short_term[1]["role"] == "assistant"

    @pytest.mark.anyio
    @patch("app.services.tts.generate_speech", return_value=b"fake-mp3-bytes")
    async def test_save_current_pose_reply_has_audio(
        self, mock_speech, websocket, save_dialog, memory
    ):
        with patch("app.services.intent._get_robot_state", return_value={"l_sho_pitch": 0.5}):
            await try_handle_system_intent("save this pose", websocket, save_dialog, memory=memory)
        assert len(websocket.sent) == 2
        assert websocket.sent[0]["type"] == "chat_response"
        assert websocket.sent[1] == {
            "type": "audio_response",
            "audio_base64": "ZmFrZS1tcDMtYnl0ZXM=",
            "format": "mp3",
        }

    @pytest.mark.anyio
    @patch("app.services.tts.generate_speech", return_value=b"fake-mp3-bytes")
    async def test_capture_pose_reply_has_audio(self, mock_speech, websocket, save_dialog, memory):
        state.follow_controller = MagicMock()
        state.follow_controller.trigger_capture_and_mimic = AsyncMock()
        try:
            handled = await try_handle_system_intent(
                "capture my pose", websocket, save_dialog, memory=memory
            )
        finally:
            state.follow_controller = None
        assert handled is True
        assert len(websocket.sent) == 2
        assert "Capturing your pose" in websocket.sent[0]["content"]
        assert websocket.sent[1]["type"] == "audio_response"

    @pytest.mark.anyio
    @patch("app.services.tts.generate_speech", return_value=None)
    async def test_system_intent_reply_survives_tts_failure(
        self, mock_speech, websocket, save_dialog, memory
    ):
        """A TTS failure must not crash the turn or block the text reply —
        same graceful-degradation contract as the main chat_response path."""
        with patch("app.services.intent._get_robot_state", return_value={"l_sho_pitch": 0.5}):
            handled = await try_handle_system_intent(
                "save this pose", websocket, save_dialog, memory=memory
            )
        assert handled is True
        assert len(websocket.sent) == 1
        assert websocket.sent[0]["type"] == "chat_response"


class TestHandleSaveDialogAudio:
    @pytest.mark.anyio
    @patch("app.services.tts.generate_speech", return_value=b"fake-mp3-bytes")
    async def test_awaiting_confirm_yes_reply_has_audio(self, mock_speech, websocket, save_dialog):
        save_dialog.stage = _SaveStage.AWAITING_CONFIRM
        consumed = await handle_save_dialog("yes", save_dialog, websocket)
        assert consumed is True
        assert len(websocket.sent) == 2
        assert websocket.sent[0]["content"] == "What would you like to name this pose?"
        assert websocket.sent[1]["type"] == "audio_response"

    @pytest.mark.anyio
    @patch("app.services.tts.generate_speech", return_value=b"fake-mp3-bytes")
    async def test_awaiting_name_reply_has_audio(self, mock_speech, websocket, save_dialog):
        save_dialog.stage = _SaveStage.AWAITING_NAME
        save_dialog.pending_joints = {"l_sho_pitch": 0.5}
        with patch("app.services.intent.save_pose"), patch(
            "app.services.intent._execute_on_hardware_if_connected", new_callable=AsyncMock
        ):
            consumed = await handle_save_dialog("Buddy", save_dialog, websocket)
        assert consumed is True
        assert len(websocket.sent) == 2
        assert websocket.sent[0]["content"] == "Saved as Buddy."
        assert websocket.sent[1]["type"] == "audio_response"
