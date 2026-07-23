from src.core.exceptions import AppException


class KnowledgeServiceError(AppException):
    status_code = 500
    code = "KNOWLEDGE_SERVICE_ERROR"
