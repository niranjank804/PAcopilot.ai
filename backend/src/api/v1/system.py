from fastapi import APIRouter

router = APIRouter()


@router.get("/", tags=["System"])
async def root():
    return {
        "application": "Enterprise Planning AI",
        "status": "running",
        "version": "0.1.0"
    }