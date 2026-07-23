from fastapi import APIRouter

from src.api.v1.ai import router as ai_router
from src.api.v1.auth import router as auth_router
from src.api.v1.database import router as database_router
from src.api.v1.health import router as health_router
from src.api.v1.knowledge import router as knowledge_router
from src.api.v1.monitoring import router as monitoring_router
from src.api.v1.permissions import router as permissions_router
from src.api.v1.roles import router as roles_router
from src.api.v1.system import router as system_router
from src.api.v1.tm1 import router as tm1_router
from src.api.v1.users import router as users_router

api_router = APIRouter()

api_router.include_router(system_router)
api_router.include_router(health_router)
api_router.include_router(database_router)
api_router.include_router(auth_router)
api_router.include_router(roles_router)
api_router.include_router(users_router)
api_router.include_router(permissions_router)
api_router.include_router(ai_router)
api_router.include_router(knowledge_router)
api_router.include_router(tm1_router)
api_router.include_router(monitoring_router)
