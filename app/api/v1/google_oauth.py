from fastapi import APIRouter

router = APIRouter()

@router.get("/auth/callback/google")
async def google_auth():
    return {"message": "Google Auth"}
