from fastapi import APIRouter
from sqlalchemy import text

from src.database.session import AsyncSessionLocal

router = APIRouter()


@router.get("/database", tags=["Database"])
async def database_health():
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(text("SELECT version()"))
            version = result.scalar()

        return {
            "status": "connected",
            "database": "enterprise_ai",
            "postgresql": version,
        }

    except Exception as ex:
        return {
            "status": "failed",
            "error": str(ex),
        }