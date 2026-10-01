"""Global SQLite store. Paths and settings only. No secrets."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, insert, select, update
from sqlalchemy.engine import Engine

from amix.amix_engine.appstate.schema import app_setting, provider_configuration, resource_installation, resource_job

_INI = Path(__file__).resolve().parents[2] / "alembic_app.ini"
NOT_CONFIGURED = "NOT_CONFIGURED"
READY = "READY"
INVALID = "INVALID"
MISSING = "MISSING"
INSTALLING = "INSTALLING"
FAILED = "FAILED"
_KIND_COLUMN = {
    "speech": "selected_speech_id",
    "vision": "selected_vision_id",
    "llama_runtime": "selected_llama_runtime_id",
    "gguf": "selected_gguf_model_id",
}


class SettingsRejected(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class AppState:
    network_policy: str
    selected_speech_id: str | None
    selected_vision_id: str | None
    selected_provider_id: str | None
    ffmpeg_directory: str | None
    speech_device: str
    speech_compute_type: str
    semantic_source: str | None
    selected_llama_runtime_id: str | None
    selected_gguf_model_id: str | None
    local_context_size: int | None
    local_threads: int | None


@dataclass(frozen=True)
class InstalledResource:
    resource_id: str
    kind: str
    display_name: str
    version: str | None
    local_path: str
    ownership: str
    origin: str
    license_name: str | None
    license_url: str | None
    identity: str
    runtime: str | None
    byte_size: int | None
    installed_at: str
    validated_at: str | None
    status: str
    architecture: str | None = None
    semantic_compatibility: str | None = None


@dataclass(frozen=True)
class ProviderRow:
    provider_id: str
    display_name: str
    placement: str
    base_url: str
    model_id: str
    credential_ref: str | None


def open_app(root: Path) -> AppStore:
    root.mkdir(parents=True, exist_ok=True)
    (root / "models").mkdir(exist_ok=True)
    (root / "resources").mkdir(exist_ok=True)
    (root / "logs").mkdir(exist_ok=True)
    database = root / "app.sqlite"
    _upgrade(database)
    engine = create_engine(f"sqlite:///{database.as_posix()}", future=True)
    store = AppStore(root, engine)
    store._ensure_row()
    return store


def _upgrade(database: Path) -> None:
    config = Config(str(_INI))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database.as_posix()}")
    command.upgrade(config, "head")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AppStore:
    def __init__(self, root: Path, engine: Engine) -> None:
        self.root = root
        self.engine = engine

    def close(self) -> None:
        self.engine.dispose()

    def state(self) -> AppState:
        with self.engine.connect() as connection:
            row = connection.execute(select(app_setting).where(app_setting.c.id == 1)).mappings().one()
        return AppState(
            network_policy=row["network_policy"],
            selected_speech_id=row["selected_speech_id"],
            selected_vision_id=row["selected_vision_id"],
            selected_provider_id=row["selected_provider_id"],
            ffmpeg_directory=row["ffmpeg_directory"],
            speech_device=row["speech_device"],
            speech_compute_type=row["speech_compute_type"],
            semantic_source=row["semantic_source"],
            selected_llama_runtime_id=row["selected_llama_runtime_id"],
            selected_gguf_model_id=row["selected_gguf_model_id"],
            local_context_size=row["local_context_size"],
            local_threads=row["local_threads"],
        )

    def set_network_policy(self, policy: str) -> None:
        if policy not in {"offline", "network_enabled"}:
            raise SettingsRejected("invalid_network_policy", "That network policy is not available.")
        self._update_setting(network_policy=policy)

    def set_semantic_source(self, source: str) -> None:
        if source not in {"provider", "managed_local"}:
            raise SettingsRejected("invalid_provider", "That semantic source is not available.")
        if source == "managed_local":
            state = self.state()
            if not state.selected_llama_runtime_id or not state.selected_gguf_model_id:
                raise SettingsRejected("local_model_missing", "Choose a llama.cpp runtime and a GGUF model.")
        self._update_setting(semantic_source=source)

    def set_local_limits(self, context_size: int | None, threads: int | None) -> None:
        if context_size is not None and (not isinstance(context_size, int) or context_size < 256 or context_size > 131072):
            raise SettingsRejected("invalid_local_model", "Context size must be between 256 and 131072.")
        if threads is not None and (not isinstance(threads, int) or threads < 1 or threads > 64):
            raise SettingsRejected("invalid_local_model", "Thread count must be between 1 and 64.")
        self._update_setting(local_context_size=context_size, local_threads=threads)

    def set_ffmpeg_directory(self, directory: str | None) -> None:
        self._update_setting(ffmpeg_directory=directory)

    def set_speech_runtime(self, device: str, compute_type: str) -> None:
        self._update_setting(speech_device=device, speech_compute_type=compute_type)

    def resources(self, kind: str | None = None) -> list[InstalledResource]:
        statement = select(resource_installation)
        if kind is not None:
            statement = statement.where(resource_installation.c.kind == kind)
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [_resource(row) for row in rows]

    def resource(self, resource_id: str) -> InstalledResource | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(resource_installation).where(resource_installation.c.resource_id == resource_id)
            ).mappings().first()
        return None if row is None else _resource(row)

    def add_resource(
        self,
        *,
        kind: str,
        display_name: str,
        local_path: str,
        ownership: str,
        origin: str,
        identity: str,
        runtime: str,
        version: str | None = None,
        license_name: str | None = None,
        license_url: str | None = None,
        byte_size: int | None = None,
        status: str = READY,
        architecture: str | None = None,
        semantic_compatibility: str | None = None,
    ) -> InstalledResource:
        resource_id = str(uuid.uuid4())
        now = _now()
        with self.engine.begin() as connection:
            connection.execute(insert(resource_installation).values(
                resource_id=resource_id,
                kind=kind,
                display_name=display_name[:128],
                version=version,
                local_path=local_path,
                ownership=ownership,
                origin=origin,
                license_name=license_name,
                license_url=license_url,
                identity=identity,
                runtime=runtime,
                byte_size=byte_size,
                installed_at=now,
                validated_at=now,
                status=status,
                architecture=architecture,
                semantic_compatibility=semantic_compatibility or "unknown",
            ))
        saved = self.resource(resource_id)
        if saved is None:
            raise SettingsRejected("internal_error", "The resource could not be saved.")
        column = _KIND_COLUMN.get(kind)
        if column is not None and getattr(self.state(), column) is None:
            self._update_setting(**{column: resource_id})
        return saved

    def select_resource(self, resource_id: str) -> None:
        found = self.resource(resource_id)
        if found is None or found.kind not in _KIND_COLUMN:
            raise SettingsRejected("unknown_resource", "That resource is not installed.")
        self._update_setting(**{_KIND_COLUMN[found.kind]: resource_id})

    def mark_resource(self, resource_id: str, status: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                update(resource_installation)
                .where(resource_installation.c.resource_id == resource_id)
                .values(status=status)
            )

    def delete_resource(self, resource_id: str) -> InstalledResource:
        found = self.resource(resource_id)
        if found is None:
            raise SettingsRejected("unknown_resource", "That resource is not installed.")
        state = self.state()
        with self.engine.begin() as connection:
            connection.execute(
                resource_installation.delete().where(resource_installation.c.resource_id == resource_id)
            )
        cleared = {
            column: None
            for column, selected in (
                ("selected_speech_id", state.selected_speech_id),
                ("selected_vision_id", state.selected_vision_id),
                ("selected_llama_runtime_id", state.selected_llama_runtime_id),
                ("selected_gguf_model_id", state.selected_gguf_model_id),
            )
            if selected == resource_id
        }
        if cleared:
            self._update_setting(**cleared)
        if state.semantic_source == "managed_local" and resource_id in {
            state.selected_llama_runtime_id,
            state.selected_gguf_model_id,
        }:
            self._update_setting(semantic_source="provider")
        return found

    def providers(self) -> list[ProviderRow]:
        with self.engine.connect() as connection:
            rows = connection.execute(select(provider_configuration)).mappings().all()
        return [_provider(row) for row in rows]

    def provider(self, provider_id: str) -> ProviderRow | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(provider_configuration).where(provider_configuration.c.provider_id == provider_id)
            ).mappings().first()
        return None if row is None else _provider(row)

    def save_provider(
        self,
        *,
        display_name: str,
        placement: str,
        base_url: str,
        model_id: str,
        provider_id: str | None = None,
    ) -> ProviderRow:
        if placement not in {"local", "remote"}:
            raise SettingsRejected("invalid_provider", "That provider placement is not available.")
        now = _now()
        chosen = provider_id or str(uuid.uuid4())
        existing = self.provider(chosen) if provider_id else None
        credential_ref = existing.credential_ref if existing else (f"provider:{chosen}" if placement == "remote" else None)
        with self.engine.begin() as connection:
            if existing is None:
                connection.execute(insert(provider_configuration).values(
                    provider_id=chosen,
                    display_name=display_name[:128],
                    placement=placement,
                    base_url=base_url.strip(),
                    model_id=model_id.strip(),
                    credential_ref=credential_ref,
                    created_at=now,
                ))
            else:
                connection.execute(
                    update(provider_configuration)
                    .where(provider_configuration.c.provider_id == chosen)
                    .values(
                        display_name=display_name[:128],
                        placement=placement,
                        base_url=base_url.strip(),
                        model_id=model_id.strip(),
                        credential_ref=credential_ref,
                    )
                )
        if self.state().selected_provider_id is None:
            self._update_setting(selected_provider_id=chosen)
        saved = self.provider(chosen)
        if saved is None:
            raise SettingsRejected("internal_error", "The provider could not be saved.")
        return saved

    def select_provider(self, provider_id: str) -> None:
        if self.provider(provider_id) is None:
            raise SettingsRejected("unknown_provider", "That provider is not configured.")
        self._update_setting(selected_provider_id=provider_id, semantic_source="provider")

    def delete_provider(self, provider_id: str) -> ProviderRow:
        found = self.provider(provider_id)
        if found is None:
            raise SettingsRejected("unknown_provider", "That provider is not configured.")
        with self.engine.begin() as connection:
            connection.execute(
                provider_configuration.delete().where(provider_configuration.c.provider_id == provider_id)
            )
        if self.state().selected_provider_id == provider_id:
            self._update_setting(selected_provider_id=None)
        return found

    def create_resource_job(self, kind: str, resource_id: str) -> str:
        job_id = str(uuid.uuid4())
        with self.engine.begin() as connection:
            connection.execute(insert(resource_job).values(
                job_id=job_id,
                kind=kind,
                status="QUEUED",
                progress_bp=0,
                resource_id=resource_id,
                created_at=_now(),
            ))
        return job_id

    def resource_job(self, job_id: str) -> dict | None:
        with self.engine.connect() as connection:
            row = connection.execute(select(resource_job).where(resource_job.c.job_id == job_id)).mappings().first()
        return None if row is None else dict(row)

    def update_resource_job(self, job_id: str, **fields: object) -> None:
        with self.engine.begin() as connection:
            connection.execute(update(resource_job).where(resource_job.c.job_id == job_id).values(**fields))

    def _ensure_row(self) -> None:
        with self.engine.begin() as connection:
            found = connection.execute(select(app_setting.c.id).where(app_setting.c.id == 1)).first()
            if found is None:
                connection.execute(insert(app_setting).values(
                    id=1,
                    network_policy="offline",
                    speech_device="cpu",
                    speech_compute_type="int8",
                ))

    def _update_setting(self, **fields: object) -> None:
        with self.engine.begin() as connection:
            connection.execute(update(app_setting).where(app_setting.c.id == 1).values(**fields))


def _resource(row) -> InstalledResource:
    return InstalledResource(
        resource_id=row["resource_id"],
        kind=row["kind"],
        display_name=row["display_name"],
        version=row["version"],
        local_path=row["local_path"],
        ownership=row["ownership"],
        origin=row["origin"],
        license_name=row["license_name"],
        license_url=row["license_url"],
        identity=row["identity"],
        runtime=row["runtime"],
        byte_size=row["byte_size"],
        installed_at=row["installed_at"],
        validated_at=row["validated_at"],
        status=row["status"],
        architecture=row["architecture"],
        semantic_compatibility=row["semantic_compatibility"] or "unknown",
    )


def _provider(row) -> ProviderRow:
    return ProviderRow(
        provider_id=row["provider_id"],
        display_name=row["display_name"],
        placement=row["placement"],
        base_url=row["base_url"],
        model_id=row["model_id"],
        credential_ref=row["credential_ref"],
    )
