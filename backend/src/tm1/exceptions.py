from src.core.exceptions import AppException


class TM1ConnectionError(AppException):
    status_code = 502
    code = "TM1_CONNECTION_ERROR"


class TM1OutcomeUnknownError(TM1ConnectionError):
    """The request may have reached TM1 and been applied: the connection
    dropped, it timed out, or the server or gateway failed mid-request.
    For a read that only means no answer; for a write it means nobody
    knows whether it happened, and nothing may assume it did not."""


class TM1ConnectionSuspendedError(AppException):
    """The platform owner suspended this connection: nothing may open a
    session with its credentials until it is resumed."""

    status_code = 403
    code = "TM1_CONNECTION_SUSPENDED"


class TM1AuthenticationError(AppException):
    status_code = 401
    code = "TM1_AUTHENTICATION_ERROR"


class TM1NotFoundError(AppException):
    status_code = 404
    code = "TM1_NOT_FOUND"
