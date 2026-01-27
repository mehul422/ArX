import uuid
from datetime import datetime, timezone
from typing import Any

from psycopg2.extras import Json

from app.db.session import get_connection


def create_jobs_table() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    params JSONB NOT NULL,
                    result JSONB,
                    error TEXT,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )


def create_user_inputs_table() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_inputs (
                    id TEXT PRIMARY KEY,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )


def insert_user_input(payload: dict[str, Any]) -> str:
    input_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_inputs (id, payload, created_at)
                VALUES (%s, %s, %s)
                """,
                (input_id, Json(payload), now),
            )
    return input_id


def fetch_user_input(input_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, payload, created_at
                FROM user_inputs
                WHERE id = %s
                """,
                (input_id,),
            )
            row = cur.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "payload": row[1],
        "created_at": row[2],
    }


def insert_job(job_type: str, params: dict[str, Any]) -> str:
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO jobs (id, type, status, params, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (job_id, job_type, "queued", Json(params), now, now),
            )
    return job_id


def update_job(
    job_id: str,
    status: str,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE jobs
                SET status = %s,
                    result = %s,
                    error = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (status, Json(result) if result is not None else None, error, now, job_id),
            )


def fetch_job(job_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, type, status, params, result, error, created_at, updated_at
                FROM jobs
                WHERE id = %s
                """,
                (job_id,),
            )
            row = cur.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "type": row[1],
        "status": row[2],
        "params": row[3],
        "result": row[4],
        "error": row[5],
        "created_at": row[6],
        "updated_at": row[7],
    }
