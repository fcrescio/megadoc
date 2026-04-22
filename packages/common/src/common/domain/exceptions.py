class ApplicationError(Exception):
    """Base application exception."""


class ValidationError(ApplicationError):
    """Raised when user input is invalid."""


class NotFoundError(ApplicationError):
    """Raised when a requested resource does not exist."""


class ConflictError(ApplicationError):
    """Raised when an operation would create an invalid duplicate."""


class ProcessingError(ApplicationError):
    """Raised when OCR processing fails."""

