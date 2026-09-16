"""Загрузчик статусов зарядных точек (EVSEStatus, data.geo.admin.ch / ich-tanke-strom.ch).

Один снимок на 15-минутный слот; ключ идемпотентности — слот снимка + EvseID.
Если слот уже загружен успешно, запуск пропускается без обращения к источнику.
При сбое: повторные попытки с экспоненциальной задержкой (см. src.http_client),
пропуск слота фиксируется в журнале загрузок (ops.load_log) со статусом error.
"""

import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from src.atomic_write import atomic_write_text
from src.config import CONFIG, RAW_DATA_DIR
from src.db import engine
from src.http_client import make_session
from src.run_log import has_successful_run_for_slot, start_run

SOURCE = "evse_status"


def current_slot(now: datetime | None = None) -> datetime:
    """Округляет момент времени вниз до ближайшего 15-минутного слота (UTC)."""
    now = now or datetime.now(timezone.utc)
    floored_minute = (now.minute // 15) * 15
    return now.replace(minute=floored_minute, second=0, microsecond=0)


def run() -> None:
    slot = current_slot()
    slot_iso = slot.isoformat()

    if has_successful_run_for_slot(SOURCE, slot_iso):
        with start_run(SOURCE, {"slot": slot_iso}) as ctx:
            ctx.status = "skipped"
        return

    url = CONFIG["sources"]["evse_status"]["url"]

    with start_run(SOURCE, {"slot": slot_iso}) as ctx:
        session = make_session()
        response = session.get(url, timeout=30)
        ctx.response_code = response.status_code
        response.raise_for_status()

        raw_text = response.text
        ctx.content_checksum = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()

        raw_path = RAW_DATA_DIR / "evse_status" / f"{slot.strftime('%Y%m%dT%H%M%SZ')}.json"
        atomic_write_text(raw_path, raw_text)
        ctx.raw_file_path = str(raw_path)

        payload = response.json()
        records = []
        missing_id = 0
        for group in payload.get("EVSEStatuses", []):
            for record in group.get("EVSEStatusRecord", []):
                evse_id = record.get("EvseID")
                status = record.get("EVSEStatus")
                if not evse_id:
                    missing_id += 1
                    continue
                records.append({"evse_id": evse_id, "status": status})

        ctx.rows_received = len(records) + missing_id
        ctx.missing_id_count = missing_id

        seen = set()
        deduped = []
        duplicate_count = 0
        for r in records:
            if r["evse_id"] in seen:
                duplicate_count += 1
                continue
            seen.add(r["evse_id"])
            deduped.append(r)
        ctx.duplicate_count = duplicate_count

        run_id = ctx.run_id
        with engine.begin() as conn:
            for r in deduped:
                conn.execute(
                    text(
                        """
                        INSERT INTO raw.evse_status_snapshot (slot, evse_id, status, run_id)
                        VALUES (:slot, :evse_id, :status, :run_id)
                        ON CONFLICT (slot, evse_id) DO NOTHING
                        """
                    ),
                    {"slot": slot, "evse_id": r["evse_id"], "status": r["status"], "run_id": str(run_id)},
                )
        ctx.rows_written = len(deduped)


if __name__ == "__main__":
    run()
