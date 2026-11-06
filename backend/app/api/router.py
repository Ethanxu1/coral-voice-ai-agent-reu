"""Aggregate API router for the Coral backend."""

from app.api.routes import health, intent, motion, speaker, state, websocket
from fastapi import APIRouter

router = APIRouter()
router.include_router(health.router)
router.include_router(state.router)
router.include_router(intent.router)
router.include_router(motion.router)
router.include_router(speaker.router)
router.include_router(websocket.router)
