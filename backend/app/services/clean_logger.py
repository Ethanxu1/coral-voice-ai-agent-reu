"""Human-readable structured session log.

Writes a clean, facilitator-friendly log of each session to a file under
``logs/clean_logs/<session_id>/clean_log_<timestamp>_<session_id>.log``.
Unlike the dense server/vision logs, this file contains only the conversation
flow, high-level intent routing, follow/capture stats, and real errors so a
human can quickly review what happened in a session without a deep dive into
internal debug output.
"""

from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from app.resource_path import user_data_dir


class CleanLogger:
    """Append-only, line-oriented clean log for a single session."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.started_at = datetime.now()
        timestamp = self.started_at.strftime("%Y%m%d_%H%M%S")

        # In dev this lives under the repo's logs/ folder; in a frozen install
        # it lives under ~/.coral/logs so the bundle directory stays clean.
        base_dir = user_data_dir() / "logs" / "clean_logs" / session_id
        base_dir.mkdir(parents=True, exist_ok=True)

        self.path = base_dir / f"clean_log_{timestamp}_{session_id}.log"
        self._file = open(self.path, "w", encoding="utf-8")
        self._write("SESSION", f"Session started: {session_id}")

    def _write(self, category: str, message: str, extras: Optional[dict[str, Any]] = None) -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"{ts} [{category}] {message}"
        if extras:
            # Compact JSON, sorted keys, no unicode escapes — easy to grep.
            line += f" | {json.dumps(extras, ensure_ascii=False, separators=(',', ':'), sort_keys=True, default=str)}"
        self._file.write(line + "\n")
        self._file.flush()

    # ------------------------------------------------------------------
    # Conversation
    # ------------------------------------------------------------------
    def user_message(self, text: str, extras: Optional[dict[str, Any]] = None) -> None:
        """Log a user message, optionally with the classified intent."""
        self._write("USER", text, extras)

    def agent_response(self, content: str, response_type: str = "chat_response", extras: Optional[dict[str, Any]] = None) -> None:
        """Log an assistant/agent response."""
        merged: dict[str, Any] = {"type": response_type}
        if extras:
            merged.update(extras)
        self._write("AGENT", content, merged)

    # ------------------------------------------------------------------
    # Intents / routing
    # ------------------------------------------------------------------
    def intent_summary(self, result: dict[str, Any], source: str = "unknown") -> dict[str, Any]:
        """Return a compact, human-readable summary of an intent result."""
        extras: dict[str, Any] = {
            "classifier": result.get("classifier"),
            "type": result.get("type"),
            "source": source,
        }
        intent_type = result.get("type")
        if intent_type == "immediate":
            extras["intent"] = result.get("intent")
            if result.get("name"):
                extras["name"] = result.get("name")
        elif intent_type == "motion":
            extras["description"] = result.get("description")
        elif intent_type == "clarification":
            extras["question"] = result.get("question")
        elif intent_type == "conversation":
            extras["text"] = result.get("text")
        reason = result.get("reason")
        if reason:
            extras["reason"] = reason
        return extras

    # ------------------------------------------------------------------
    # Follow mode
    # ------------------------------------------------------------------
    def follow_started(self) -> None:
        self._write("FOLLOW", "started")

    def follow_stopped(self, reason: Optional[str] = None) -> None:
        extras = {"reason": reason} if reason else None
        self._write("FOLLOW", "stopped", extras)

    def follow_tick(self, dispatches: int, skips: int, empty_targets: int) -> None:
        """Log a periodic follow-mode health snapshot."""
        self._write(
            "FOLLOW",
            "tick",
            {
                "dispatches": dispatches,
                "skips": skips,
                "empty_targets": empty_targets,
            },
        )

    def follow_event(self, message: str, extras: Optional[dict[str, Any]] = None) -> None:
        """Log a one-off follow-mode event (seed, tracking start, etc.)."""
        self._write("FOLLOW", message, extras)

    def follow_error(self, message: str, exc: Optional[BaseException] = None) -> None:
        extras: dict[str, Any] = {}
        if exc is not None:
            extras["exception"] = str(exc)
            extras["traceback"] = traceback.format_exception_only(type(exc), exc)[-1].strip()
        self._write("FOLLOW", f"error: {message}", extras or None)

    # ------------------------------------------------------------------
    # Capture mode
    # ------------------------------------------------------------------
    def capture_started(self) -> None:
        self._write("CAPTURE", "started")

    def capture_stage(self, stage: str, extras: Optional[dict[str, Any]] = None) -> None:
        self._write("CAPTURE", stage, extras)

    def capture_error(self, message: str, exc: Optional[BaseException] = None) -> None:
        extras: dict[str, Any] = {}
        if exc is not None:
            extras["exception"] = str(exc)
            extras["traceback"] = traceback.format_exception_only(type(exc), exc)[-1].strip()
        self._write("CAPTURE", f"error: {message}", extras or None)

    # ------------------------------------------------------------------
    # Errors / misc
    # ------------------------------------------------------------------
    def error(self, message: str, exc: Optional[BaseException] = None) -> None:
        """Log a real error with optional exception details."""
        extras: dict[str, Any] = {}
        if exc is not None:
            extras["exception"] = str(exc)
            try:
                extras["traceback"] = traceback.format_exception_only(type(exc), exc)[-1].strip()
            except Exception:
                pass
        self._write("ERROR", message, extras or None)

    def websocket_event(self, event: str, extras: Optional[dict[str, Any]] = None) -> None:
        self._write("WS", event, extras)

    def close(self) -> None:
        """Flush and close the log file."""
        try:
            self._write("SESSION", f"Session ended: {self.session_id}")
        finally:
            self._file.close()


# Per-session registry so both the WebSocket connection and the HTTP
# /classify-intent endpoint can write to the same clean log file.
_clean_loggers: dict[str, CleanLogger] = {}


def get_or_create_logger(session_id: str) -> CleanLogger:
    """Return an existing clean logger for the session or create one."""
    if session_id not in _clean_loggers:
        _clean_loggers[session_id] = CleanLogger(session_id)
    return _clean_loggers[session_id]


def get_clean_logger(session_id: Optional[str] = None) -> Optional[CleanLogger]:
    """Return a clean logger by session id, or the most recently created one."""
    if session_id is not None:
        return _clean_loggers.get(session_id)
    # Fallback: most recent logger (useful for background tasks with no session).
    if _clean_loggers:
        return next(reversed(_clean_loggers.values()))
    return None


def close_logger(session_id: str) -> None:
    """Close and remove the logger for a session."""
    logger = _clean_loggers.pop(session_id, None)
    if logger is not None:
        logger.close()
