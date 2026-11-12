"""Subprocess fixture: one worker process sending one tus PATCH (#7543 S08).

Every invocation is its own Python process with its own in-memory lock
registry, exactly like one worker of a multi-worker host. It serves the shared
tus core through a fake lane and sends a single PATCH to an upload that already
exists on the shared disk (``PADIEM_TUS_UPLOAD_DIR``).

The one argument is the path of a JSON job file:

    upload_id, user_id, offset, fill, size   the chunk: ``size`` bytes of ``fill``
    result                                   where the answer is written
    finalize_log                             one appended line per completion
    hold, release (optional)                 marker files that keep the chunk open

With ``hold``/``release`` the body is sent in two halves. The second half is
only produced when the app asks for more body, so ``hold`` appears exactly when
this process is inside the PATCH, past its locks and waiting on the chunk; it
then stays there until ``release`` exists. Nothing here opens a socket.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

CHUNK = "application/offset+octet-stream"


def main(argv: list[str]) -> int:
    import httpx
    from starlette.applications import Starlette
    from starlette.routing import Route

    from app.tus_core import TusLane, tus_resource

    job = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    payload = job["fill"].encode("ascii") * int(job["size"])
    hold = job.get("hold")
    release = job.get("release")

    async def identity(request):
        return {"user_id": job["user_id"]}, None

    async def finalize(request, data_path, meta):
        with open(data_path, "rb") as handle:
            stored = handle.read()
        # Append mode keeps two processes' lines apart; one line is one
        # completion, whoever ran it.
        with open(job["finalize_log"], "a", encoding="utf-8") as log:
            log.write(json.dumps({"pid": os.getpid(), "stored": stored.decode("ascii")}) + "\n")
        return {"status": 201, "body": {"ok": True, "bytes": len(stored)}}

    lane = TusLane(
        name="fake",
        identity=identity,
        finalize=finalize,
        accepts=lambda media_type: True,
        location=lambda request, meta: "/api/fake/tus/" + meta["upload_id"],
    )

    async def item(request):
        return await tus_resource(request, lane)

    app = Starlette(routes=[
        Route("/api/fake/tus/{upload_id}", item, methods=["HEAD", "PATCH", "GET"]),
    ])

    async def body():
        if not hold:
            yield payload
            return
        half = len(payload) // 2
        yield payload[:half]
        Path(hold).touch()
        while not Path(release).exists():
            await asyncio.sleep(0.01)
        yield payload[half:]

    async def send():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://tus.test") as client:
            return await client.patch(
                "/api/fake/tus/" + job["upload_id"],
                content=body(),
                headers={
                    "Tus-Resumable": "1.0.0",
                    "Upload-Offset": str(job["offset"]),
                    "Content-Type": CHUNK,
                },
            )

    answer = asyncio.run(send())
    code = ""
    if answer.content:
        try:
            code = (answer.json().get("error") or {}).get("code", "")
        except ValueError:
            code = "unreadable"
    Path(job["result"]).write_text(
        json.dumps({"status": answer.status_code, "code": code, "pid": os.getpid()}),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
