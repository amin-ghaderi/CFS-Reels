"""Start the local engine: python -m amix.amix_engine.service"""
from __future__ import annotations

import asyncio
import json
import logging
import sys

import uvicorn

from amix.amix_engine.service.app import create_app
from amix.amix_engine.service.config import ServiceConfig
from amix.amix_engine.service.owner import exit_when_owner_exits
from amix.amix_engine.service.runtime import EngineRuntime


def startup_record(host: str, port: int, token: str) -> str:
    payload = {"event": "amix.engine.ready", "host": host, "port": port, "token": token}
    return json.dumps(payload, separators=(",", ":")) + "\n"


def run(config: ServiceConfig | None = None) -> None:
    selected = config or ServiceConfig.from_argv()
    logging.basicConfig(
        level=getattr(logging, selected.log_level.upper(), logging.INFO),
        stream=sys.stderr,
        format="%(levelname)s %(name)s %(message)s",
    )
    runtime = EngineRuntime(selected)
    app = create_app(runtime)
    server_config = uvicorn.Config(
        app,
        host=selected.host,
        port=selected.port,
        log_config=None,
        access_log=False,
        lifespan="on",
    )
    server = uvicorn.Server(server_config)

    async def _serve_and_announce() -> None:
        task = asyncio.create_task(server.serve())
        while not server.started:
            await asyncio.sleep(0.01)
            if task.done():
                break
        if server.started and server.servers:
            sock = server.servers[0].sockets[0]
            bound_host, bound_port = sock.getsockname()[:2]
            sys.stdout.write(startup_record(bound_host, bound_port, runtime.token))
            sys.stdout.flush()
        await task

    asyncio.run(_serve_and_announce())


def main() -> None:
    exit_when_owner_exits()
    try:
        run()
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
