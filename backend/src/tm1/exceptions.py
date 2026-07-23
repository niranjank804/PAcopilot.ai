from src.core.exceptions import AppException


class TM1ConnectionError(AppException):
    status_code = 502
    code = "TM1_CONNECTION_ERROR"


class TM1AuthenticationError(AppException):
    status_code = 401
    code = "TM1_AUTHENTICATION_ERROR"


class TM1NotFoundError(AppException):
    status_code = 404
    code = "TM1_NOT_FOUND"
