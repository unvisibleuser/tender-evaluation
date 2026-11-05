"""Domain errors with stable, client-visible codes."""

from __future__ import annotations


class DomainError(Exception):
    status_code = 400
    code = "DOMAIN_ERROR"

    def __init__(self, message: str, *, code: str | None = None, details: object | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        self.details = details


class NotFound(DomainError):
    status_code = 404
    code = "NOT_FOUND"


class Unauthenticated(DomainError):
    status_code = 401
    code = "UNAUTHENTICATED"


class Forbidden(DomainError):
    status_code = 403
    code = "FORBIDDEN"


class Conflict(DomainError):
    status_code = 409
    code = "CONFLICT"


class InvalidTransition(Conflict):
    code = "INVALID_TRANSITION"


class VersionConflict(Conflict):
    code = "VERSION_CONFLICT"


class CommercialSealed(Conflict):
    code = "COMMERCIAL_SEALED"


class TechnicalSealed(Conflict):
    code = "TECHNICAL_SEALED"


class ValidationFailed(DomainError):
    status_code = 422
    code = "VALIDATION_FAILED"


class InvalidDocument(DomainError):
    status_code = 422
    code = "INVALID_DOCUMENT"
