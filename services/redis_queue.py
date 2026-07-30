"""Small Redis-backed store for scheduled transactional sender jobs.

This intentionally uses only Python's standard library so the API can start
without another Python package. Redis itself must still be running.
"""

from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timezone
from typing import Any


class RedisQueueError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RedisConnection:
    def __init__(self) -> None:
        self.host = os.getenv("REDIS_HOST", "127.0.0.1")
        self.port = int(os.getenv("REDIS_PORT", "6379"))
        self.password = os.getenv("REDIS_PASSWORD")

    @staticmethod
    def _encode(parts: list[str]) -> bytes:
        encoded = [f"*{len(parts)}\r\n".encode()]
        for part in parts:
            value = str(part).encode("utf-8")
            encoded.extend((f"${len(value)}\r\n".encode(), value, b"\r\n"))
        return b"".join(encoded)

    @staticmethod
    def _read_line(stream) -> bytes:
        line = stream.readline()
        if not line.endswith(b"\r\n"):
            raise RedisQueueError("Redis returned an incomplete response.")
        return line[:-2]

    def _read_response(self, stream):
        prefix = stream.read(1)
        if not prefix:
            raise RedisQueueError("Redis closed the connection.")
        if prefix == b"+":
            return self._read_line(stream).decode("utf-8")
        if prefix == b"-":
            raise RedisQueueError(self._read_line(stream).decode("utf-8"))
        if prefix == b":":
            return int(self._read_line(stream))
        if prefix == b"$":
            length = int(self._read_line(stream))
            if length == -1:
                return None
            value = stream.read(length)
            if len(value) != length or stream.read(2) != b"\r\n":
                raise RedisQueueError("Redis returned an incomplete bulk response.")
            return value.decode("utf-8")
        if prefix == b"*":
            count = int(self._read_line(stream))
            return [self._read_response(stream) for _ in range(count)] if count >= 0 else None
        raise RedisQueueError("Redis returned an unknown response type.")

    def command(self, *parts: str):
        try:
            with socket.create_connection((self.host, self.port), timeout=3) as connection:
                with connection.makefile("rwb") as stream:
                    if self.password:
                        stream.write(self._encode(["AUTH", self.password]))
                        stream.flush()
                        self._read_response(stream)
                    stream.write(self._encode([str(part) for part in parts]))
                    stream.flush()
                    return self._read_response(stream)
        except (OSError, ValueError) as exc:
            raise RedisQueueError(
                "Redis is unavailable. Start it with `docker compose up -d redis` and try again."
            ) from exc


class TransactionalQueue:
    READY_KEY = "smartmailer:transactional:ready"
    PROCESSING_KEY = "smartmailer:transactional:processing"
    JOB_PREFIX = "smartmailer:transactional:job:"
    RECIPIENTS_PREFIX = "smartmailer:transactional:recipients:"

    def __init__(self) -> None:
        self.redis = RedisConnection()

    @staticmethod
    def _key(job_id: str) -> str:
        return f"{TransactionalQueue.JOB_PREFIX}{job_id}"

    @staticmethod
    def _recipients_key(job_id: str) -> str:
        return f"{TransactionalQueue.RECIPIENTS_PREFIX}{job_id}"

    def ping(self) -> bool:
        return self.redis.command("PING") == "PONG"

    def save(self, job: dict[str, Any]) -> None:
        self.redis.command("SET", self._key(job["id"]), json.dumps(job, separators=(",", ":")))

    def get(self, job_id: str) -> dict[str, Any] | None:
        raw = self.redis.command("GET", self._key(job_id))
        return json.loads(raw) if raw else None

    def save_recipients(self, job_id: str, recipients: list[dict[str, Any]]) -> None:
        """Store recipient records separately, so large jobs do not rewrite them per batch."""
        key = self._recipients_key(job_id)
        for start in range(0, len(recipients), 500):
            values = [json.dumps(item, separators=(",", ":")) for item in recipients[start : start + 500]]
            self.redis.command("RPUSH", key, *values)

    def pop_recipients(self, job_id: str, count: int) -> list[dict[str, Any]]:
        values = self.redis.command("LPOP", self._recipients_key(job_id), str(count))
        if values is None:
            return []
        if isinstance(values, str):
            values = [values]
        return [json.loads(value) for value in values]

    def delete_recipients(self, job_id: str) -> None:
        self.redis.command("DEL", self._recipients_key(job_id))

    def schedule(self, job_id: str, run_at_epoch: float) -> None:
        self.redis.command("ZADD", self.READY_KEY, str(run_at_epoch), job_id)

    def claim_due(self, now_epoch: float) -> str | None:
        due = self.redis.command("ZRANGEBYSCORE", self.READY_KEY, "-inf", str(now_epoch), "LIMIT", "0", "1")
        if not due:
            return None
        job_id = due[0]
        if self.redis.command("ZREM", self.READY_KEY, job_id) != 1:
            return None
        self.redis.command("ZADD", self.PROCESSING_KEY, str(now_epoch), job_id)
        return job_id

    def finish_claim(self, job_id: str) -> None:
        self.redis.command("ZREM", self.PROCESSING_KEY, job_id)

    def recover_stale_claims(self, older_than_epoch: float) -> int:
        job_ids = self.redis.command(
            "ZRANGEBYSCORE", self.PROCESSING_KEY, "-inf", str(older_than_epoch)
        ) or []
        for job_id in job_ids:
            if self.redis.command("ZREM", self.PROCESSING_KEY, job_id) == 1:
                self.schedule(job_id, older_than_epoch)
        return len(job_ids)
