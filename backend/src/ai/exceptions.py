from src.core.exceptions import AppException


class AIProviderError(AppException):
    status_code = 502
    code = "AI_PROVIDER_ERROR"


class AIProviderRateLimitError(AIProviderError):
    status_code = 429
    code = "AI_PROVIDER_RATE_LIMIT"


class AIProviderAuthenticationError(AIProviderError):
    status_code = 500
    code = "AI_PROVIDER_CONFIG_ERROR"
