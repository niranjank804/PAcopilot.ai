from fastapi import APIRouter

from src.api.v1.ai import router as ai_router
from src.api.v1.auth import router as auth_router
from src.api.v1.billing import router as billing_router
from src.api.v1.database import router as database_router
from src.api.v1.gateway import admin_router as gateway_admin_router
from src.api.v1.gateway import agent_router as gateway_agent_router
from src.api.v1.health import router as health_router
from src.api.v1.knowledge import router as knowledge_router
from src.api.v1.memory import router as memory_router
from src.api.v1.team import router as team_router
from src.api.v1.monitors import router as monitors_router
from src.api.v1.command_center import router as command_center_router
from src.api.v1.learning import router as learning_router
from src.api.v1.monitoring import router as monitoring_router
from src.api.v1.permissions import router as permissions_router
from src.api.v1.reports import router as reports_router
from src.api.v1.roles import router as roles_router
from src.api.v1.internal import router as internal_router
from src.api.v1.system import router as system_router
from src.api.v1.uploads import router as uploads_router
from src.api.v1.tm1 import router as tm1_router
from src.api.v1.signups import router as signups_router
from src.api.v1.users import router as users_router
from src.api.v1.worker import router as worker_router

api_router = APIRouter()

api_router.include_router(system_router)
api_router.include_router(health_router)
api_router.include_router(database_router)
api_router.include_router(auth_router)
api_router.include_router(roles_router)
api_router.include_router(users_router)
api_router.include_router(signups_router)
api_router.include_router(permissions_router)
api_router.include_router(ai_router)
api_router.include_router(memory_router)
api_router.include_router(team_router)
api_router.include_router(monitors_router)
api_router.include_router(command_center_router)
api_router.include_router(knowledge_router)
api_router.include_router(gateway_admin_router)
api_router.include_router(tm1_router)
api_router.include_router(learning_router)
api_router.include_router(monitoring_router)
api_router.include_router(billing_router)
api_router.include_router(reports_router)
# Worker plane: authenticated as a machine, not a user. Separate router
# so the two auth families never share a dependency by accident.
api_router.include_router(worker_router)
api_router.include_router(gateway_agent_router)
api_router.include_router(internal_router)
api_router.include_router(uploads_router)
