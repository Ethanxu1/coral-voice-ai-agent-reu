"""Aggregate API router for the Coral backend."""

from fastapi import APIRouter

from app.api.routes import health, intent, motion, state, websocket

router = APIRouter()
router.include_router(health.router)
router.include_router(state.router)
router.include_router(intent.router)
router.include_router(motion.router)
router.include_router(websocket.router)
