import sys

from loguru import logger

from src.core.config import settings
from src.middleware.request_context import current_request_id

logger.remove()


def _stamp_request_id(record: dict) -> None:
    """Every line carries the id of the request that produced it, so one
    user action's fan-out (an agent turn, its tool calls, their TM1
    requests) can be read back as one story."""

    record["extra"].setdefault("request_id", current_request_id() or "-")


logger.configure(patcher=_stamp_request_id)

logger.add(
    sys.stdout,
    level="INFO",
    format=(
        "{time:YYYY-MM-DD HH:mm:ss} | "
        "{level:<8} | "
        "{extra[request_id]} | "
        "{name}:{function}:{line} | "
        "{message}"
    ),
)

# A file sink only where one was asked for. The hosted platforms collect
# stdout, their disks are ephemeral or read-only, and a sink that cannot
# be opened would fail this import before the app served anything.
if settings.LOG_FILE:
    logger.add(
        settings.LOG_FILE,
        rotation="10 MB",
        retention="30 days",
        level="INFO",
        format=(
            "{time:YYYY-MM-DD HH:mm:ss} | "
            "{level:<8} | "
            "{extra[request_id]} | "
            "{name}:{function}:{line} | "
            "{message}"
        ),
    )

app_logger = logger
