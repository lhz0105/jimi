"""领域异常：统一映射到 HTTP 错误信封 {"error": {code, message, detail}}。"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    code = "APP_ERROR"
    http_status = 400

    def __init__(self, message: str, *, detail: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class UnauthorizedError(AppError):
    code = "UNAUTHORIZED"
    http_status = 401


class NotFoundError(AppError):
    code = "NOT_FOUND"
    http_status = 404


class ConflictError(AppError):
    code = "CONFLICT"
    http_status = 409


class SandboxViolation(AppError):
    code = "SANDBOX_VIOLATION"
    http_status = 403


class BudgetExceeded(AppError):
    code = "BUDGET_EXCEEDED"
    http_status = 429


class RunCancelled(AppError):
    code = "RUN_CANCELLED"
    http_status = 409


class InvalidRunState(AppError):
    code = "INVALID_RUN_STATE"
    http_status = 409


class ExternalServiceError(AppError):
    code = "EXTERNAL_SERVICE_ERROR"
    http_status = 502


class ServiceUnavailableError(AppError):
    code = "SERVICE_UNAVAILABLE"
    http_status = 503


class ConfigError(AppError):
    code = "CONFIG_ERROR"
    http_status = 500


class PayloadTooLarge(AppError):
    code = "PAYLOAD_TOO_LARGE"
    http_status = 413
