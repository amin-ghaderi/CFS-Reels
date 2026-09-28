"""Small engine-process settings. Not a general configuration system."""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass

LOOPBACK_HOST = "127.0.0.1"


@dataclass(frozen=True)
class ServiceConfig:
    host: str = LOOPBACK_HOST
    port: int = 0
    shutdown_timeout_s: float = 2.0
    worker_count: int = 2
    session_token: str | None = None
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        if self.host != LOOPBACK_HOST:
            raise ValueError("AMIX engine binds only to 127.0.0.1")
        if self.port < 0 or self.port > 65535:
            raise ValueError("port is out of range")
        if self.shutdown_timeout_s <= 0:
            raise ValueError("shutdown timeout must be positive")
        if self.worker_count < 1:
            raise ValueError("worker count must be positive")

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> ServiceConfig:
        env = os.environ if environ is None else environ
        token = env.get("AMIX_SESSION_TOKEN") or None
        return cls(
            host=env.get("AMIX_HOST", LOOPBACK_HOST),
            port=int(env.get("AMIX_PORT", "0")),
            shutdown_timeout_s=float(env.get("AMIX_SHUTDOWN_TIMEOUT", "2")),
            worker_count=int(env.get("AMIX_WORKERS", "2")),
            session_token=token,
            log_level=env.get("AMIX_LOG_LEVEL", "INFO"),
        )

    @classmethod
    def from_argv(cls, argv: list[str] | None = None) -> ServiceConfig:
        base = cls.from_env()
        parser = argparse.ArgumentParser(prog="amix-engine")
        parser.add_argument("--host", default=base.host)
        parser.add_argument("--port", type=int, default=base.port)
        parser.add_argument("--token", default=base.session_token)
        parser.add_argument("--shutdown-timeout", type=float, default=base.shutdown_timeout_s)
        parser.add_argument("--workers", type=int, default=base.worker_count)
        parser.add_argument("--log-level", default=base.log_level)
        args = parser.parse_args(argv)
        return cls(
            host=args.host,
            port=args.port,
            shutdown_timeout_s=args.shutdown_timeout,
            worker_count=args.workers,
            session_token=args.token,
            log_level=args.log_level,
        )
