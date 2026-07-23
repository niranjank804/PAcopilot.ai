class AppException(Exception):
    status_code = 400
    code = "APP_ERROR"

    def __init__(
        self,
        message: str,
        code: str | None = None,
    ):
        self.message = message

        if code is not None:
            self.code = code

        super().__init__(message)


class NotFoundException(AppException):
    status_code = 404
    code = "NOT_FOUND"


class ConflictException(AppException):
    status_code = 409
    code = "CONFLICT"


class ValidationException(AppException):
    status_code = 422
    code = "VALIDATION_ERROR"


class PermissionDeniedException(AppException):
    status_code = 403
    code = "PERMISSION_DENIED"


class AuthenticationException(AppException):
    status_code = 401
    code = "AUTHENTICATION_ERROR"


class QuotaExceededException(AppException):
    status_code = 429
    code = "QUOTA_EXCEEDED"
