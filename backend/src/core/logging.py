from loguru import logger
import sys

logger.remove()

logger.add(
    sys.stdout,
    level="INFO",
    format=(
        "{time:YYYY-MM-DD HH:mm:ss} | "
        "{level:<8} | "
        "{name}:{function}:{line} | "
        "{message}"
    ),
)

logger.add(
    "logs/application.log",
    rotation="10 MB",
    retention="30 days",
    level="INFO",
)

app_logger = logger