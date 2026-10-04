"""A scripted, deterministic HTTP/1.1 server for transport-level tests.

It exists so httpcore produces real trace events: `httpx.MockTransport` skips
the connection pool and never emits them.  Stdlib only, loopback only.

Each request consumes the next `Reply` in the script (the last one repeats).
A `Reply` fixes the delay before headers, the status and headers, the body as
a list of chunks with optional per-chunk delays, optional gzip of the body, and
an optional close part-way through the body.  Connections are kept alive, so a
second request can reuse the first connection.
"""
from __future__ import annotations

import asyncio
import json
import zlib
from dataclasses import dataclass, field
from typing import Any, Sequence


@dataclass(frozen=True)
class Reply:
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    chunks: Sequence[bytes] = (b"{}",)
    # Seconds to wait before each chunk; shorter than `chunks` means 0 for the rest.
    chunk_delays: Sequence[float] = ()
    header_delay: float = 0.0
    gzip: bool = False
    # Stop after this many chunks and close the socket without ending the body.
    close_after_chunks: int | None = None
    # Stream as chunked transfer encoding (needed for SSE and multi-chunk bodies).
    chunked: bool | None = None


def json_reply(payload: Any, **kwargs: Any) -> Reply:
    headers = {"Content-Type": "application/json", **kwargs.pop("headers", {})}
    return Reply(headers=headers, chunks=(json.dumps(payload).encode(),), **kwargs)


def sse_event(payload: Any) -> bytes:
    return b"data: " + json.dumps(payload).encode() + b"\n\n"


SSE_KEEPALIVE = b": keepalive\n\n"
SSE_DONE = b"data: [DONE]\n\n"


def sse_reply(frames: Sequence[bytes], **kwargs: Any) -> Reply:
    headers = {"Content-Type": "text/event-stream", **kwargs.pop("headers", {})}
    return Reply(headers=headers, chunks=tuple(frames), chunked=True, **kwargs)


class TransportResponder:
    def __init__(self, script: Sequence[Reply], *, port: int = 0) -> None:
        self._script = list(script)
        self.requests: list[dict[str, Any]] = []
        self.connections = 0
        self._server: asyncio.AbstractServer | None = None
        self._writers: set[asyncio.StreamWriter] = set()
        self.port = port  # 0: any free port; a fixed port keeps request bytes equal across runs

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    async def __aenter__(self) -> "TransportResponder":
        self._server = await asyncio.start_server(self._serve, "127.0.0.1", self.port)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc: object) -> None:
        assert self._server is not None
        self._server.close()
        # From Python 3.12, wait_closed() waits until every accepted connection
        # is closed, so a kept-alive or deliberately stalled connection would
        # hang the test here: close them first.
        for writer in list(self._writers):
            writer.close()
        await self._server.wait_closed()

    def _next_reply(self) -> Reply:
        index = min(len(self.requests) - 1, len(self._script) - 1)
        return self._script[index]

    async def _serve(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.connections += 1
        self._writers.add(writer)
        try:
            while True:
                head = await reader.readuntil(b"\r\n\r\n")
                lines = head.decode("latin-1").split("\r\n")
                headers = {
                    k.lower(): v.strip()
                    for k, _, v in (line.partition(":") for line in lines[1:] if line)
                }
                body = await reader.readexactly(int(headers.get("content-length", 0)))
                self.requests.append(
                    {"line": lines[0], "headers": headers, "body": body}
                )
                if not await self._reply(writer, self._next_reply()):
                    break
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            self._writers.discard(writer)
            writer.close()

    async def _reply(self, writer: asyncio.StreamWriter, reply: Reply) -> bool:
        """Send one reply; return False when the connection must be dropped."""
        await asyncio.sleep(reply.header_delay)
        chunks = list(reply.chunks)
        if reply.gzip:
            # One gzip stream, sync-flushed per chunk so each chunk decodes alone.
            compressor = zlib.compressobj(wbits=31)
            chunks = [
                compressor.compress(c) + compressor.flush(zlib.Z_SYNC_FLUSH)
                for c in chunks
            ] + [compressor.flush()]
        chunked = reply.chunked if reply.chunked is not None else len(chunks) > 1
        headers = dict(reply.headers)
        if reply.gzip:
            headers["Content-Encoding"] = "gzip"
        if chunked:
            headers["Transfer-Encoding"] = "chunked"
        else:
            headers["Content-Length"] = str(sum(len(c) for c in chunks))
        status_line = f"HTTP/1.1 {reply.status} X\r\n"
        writer.write(
            status_line.encode()
            + "".join(f"{k}: {v}\r\n" for k, v in headers.items()).encode()
            + b"\r\n"
        )
        await writer.drain()
        for index, chunk in enumerate(chunks):
            if reply.close_after_chunks is not None and index >= reply.close_after_chunks:
                return False
            if index < len(reply.chunk_delays):
                await asyncio.sleep(reply.chunk_delays[index])
            writer.write(
                b"%x\r\n%s\r\n" % (len(chunk), chunk) if chunked else chunk
            )
            await writer.drain()
        if reply.close_after_chunks is not None:
            return False
        if chunked:
            writer.write(b"0\r\n\r\n")
            await writer.drain()
        return True
