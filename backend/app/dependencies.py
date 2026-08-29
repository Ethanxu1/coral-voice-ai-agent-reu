"""FastAPI dependency injection helpers."""

from fastapi import Request

from app.state import AppState, state


def get_app_state() -> AppState:
    """Return the global application state singleton."""
    return state


def get_simulator(request: Request):
    """Return the running simulator from the global state."""
    return state.simulator
