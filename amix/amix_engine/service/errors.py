"""Errors the HTTP layer maps to structured responses. No stack traces."""


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class InvalidProjectPath(ValueError):
    """The project path payload cannot be resolved."""


class UnknownProjectHandle(RuntimeError):
    """This engine process does not have the handle open."""


class ProjectAlreadyOpen(RuntimeError):
    """This process already holds the project. The existing handle stays in use."""

    def __init__(self, handle: str) -> None:
        super().__init__(handle)
        self.handle = handle


class ProjectCloseTimeout(RuntimeError):
    """A job was still active when the close deadline passed. The lock stays held."""
