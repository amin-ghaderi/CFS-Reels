"""Storage failures a caller can handle. Ordinary SQLAlchemy errors are not wrapped."""


class ProjectAlreadyLocked(RuntimeError):
    """Another local engine process already holds the project write lock."""


class ProjectDatabaseInvalid(RuntimeError):
    """The project directory has no usable database."""


class SchemaMismatch(RuntimeError):
    """The database schema is not the revision this engine can open."""


class MediaMissing(FileNotFoundError):
    """The asset's media file is not at the stored location."""


class UnknownJob(RuntimeError):
    """No processing job has this id in the open project."""


class InvalidJobState(RuntimeError):
    """The job cannot move from its current status to the requested one."""


class JobSpecRejected(ValueError):
    """The job specification contains a field that must not be stored."""
