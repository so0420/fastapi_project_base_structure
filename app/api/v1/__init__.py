from fastapi import APIRouter

from .google_oauth import router as google_oauth_router

router = APIRouter()
router.include_router(google_oauth_router, prefix="/auth", tags=["auth"])

__all__ = ["router"]
