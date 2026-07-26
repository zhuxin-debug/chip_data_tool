class DataToolError(ValueError):
    """Base class for user-facing validation errors."""


class ParseError(DataToolError):
    """Raised when input data cannot be parsed safely."""


class OperationError(DataToolError):
    """Raised when a bit operation is invalid for the current data."""


class MappingError(DataToolError):
    """Raised when a field mapping is malformed or ambiguous."""
