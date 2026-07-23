from src.core.exceptions import AppException


class EmailDeliveryError(AppException):
    status_code = 500
    code = "EMAIL_DELIVERY_ERROR"
