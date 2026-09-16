import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import text

from src.db import engine


class RunContext:
    def __init__(self, run_id: uuid.UUID, source: str):
        self.run_id = run_id
        self.source = source
        self.status = "success"
        self.response_code = None
        self.attempts = 1
        self.changed_at = None
        self.content_checksum = None
        self.raw_file_path = None
        self.rows_received = None
        self.rows_written = None
        self.duplicate_count = None
        self.missing_id_count = None
        self.error_text = None


@contextmanager
def start_run(source: str, params: dict | None = None):
    """Регистрирует запуск в ops.load_log (строка создаётся сразу, чтобы raw-таблицы
    могли ссылаться на run_id по внешнему ключу) и обновляет её по завершении,
    включая случай необработанного исключения (status=error)."""
    run_id = uuid.uuid4()
    started_at = datetime.now(timezone.utc)
    ctx = RunContext(run_id, source)

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO ops.load_log (run_id, source, started_at, status, params)
                VALUES (:run_id, :source, :started_at, 'running', :params)
                """
            ),
            {"run_id": str(run_id), "source": source, "started_at": started_at, "params": json.dumps(params or {})},
        )

    try:
        yield ctx
    except Exception as exc:
        ctx.status = "error"
        ctx.error_text = str(exc)
        raise
    finally:
        finished_at = datetime.now(timezone.utc)
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE ops.load_log SET
                        finished_at = :finished_at,
                        status = :status,
                        response_code = :response_code,
                        attempts = :attempts,
                        changed_at = :changed_at,
                        content_checksum = :content_checksum,
                        raw_file_path = :raw_file_path,
                        rows_received = :rows_received,
                        rows_written = :rows_written,
                        duplicate_count = :duplicate_count,
                        missing_id_count = :missing_id_count,
                        error_text = :error_text
                    WHERE run_id = :run_id
                    """
                ),
                {
                    "run_id": str(run_id),
                    "finished_at": finished_at,
                    "status": ctx.status,
                    "response_code": ctx.response_code,
                    "attempts": ctx.attempts,
                    "changed_at": ctx.changed_at,
                    "content_checksum": ctx.content_checksum,
                    "raw_file_path": ctx.raw_file_path,
                    "rows_received": ctx.rows_received,
                    "rows_written": ctx.rows_written,
                    "duplicate_count": ctx.duplicate_count,
                    "missing_id_count": ctx.missing_id_count,
                    "error_text": ctx.error_text,
                },
            )


def has_successful_run_for_slot(source: str, slot_iso: str) -> bool:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT 1 FROM ops.load_log
                WHERE source = :source
                  AND status = 'success'
                  AND params ->> 'slot' = :slot
                LIMIT 1
                """
            ),
            {"source": source, "slot": slot_iso},
        ).first()
        return row is not None
