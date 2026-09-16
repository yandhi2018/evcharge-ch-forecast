"""Загрузчик справочника зарядных точек (EVSEData, data.geo.admin.ch / ich-tanke-strom.ch).

Полный справочник сравнивается с ранее сохранённым состоянием по хэшу содержимого
каждой записи; сохраняются только изменившиеся записи. Ключ идемпотентности —
EvseID + хэш записи. Предыдущая версия остаётся действующей до следующего успешного запуска.
"""

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import text

from src.atomic_write import atomic_write_text
from src.config import CONFIG, RAW_DATA_DIR
from src.db import engine
from src.http_client import make_session
from src.run_log import start_run

SOURCE = "evse_data"


def _record_hash(record: dict) -> str:
    canonical = json.dumps(record, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def run() -> None:
    url = CONFIG["sources"]["evse_data"]["url"]
    now = datetime.now(timezone.utc)

    with start_run(SOURCE, {"date": now.date().isoformat()}) as ctx:
        session = make_session()
        response = session.get(url, timeout=120)
        ctx.response_code = response.status_code
        response.raise_for_status()

        raw_text = response.text
        ctx.content_checksum = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()

        raw_path = RAW_DATA_DIR / "evse_data" / f"{now.strftime('%Y%m%dT%H%M%SZ')}.json"
        atomic_write_text(raw_path, raw_text)
        ctx.raw_file_path = str(raw_path)

        payload = json.loads(raw_text)
        records = []
        missing_id = 0
        for group in payload.get("EVSEData", []):
            for record in group.get("EVSEDataRecord", []):
                evse_id = record.get("EvseID")
                if not evse_id:
                    missing_id += 1
                    continue
                records.append((evse_id, record))

        ctx.rows_received = len(records) + missing_id
        ctx.missing_id_count = missing_id

        written = 0
        with engine.begin() as conn:
            for evse_id, record in records:
                content_hash = _record_hash(record)
                result = conn.execute(
                    text(
                        """
                        INSERT INTO raw.evse_data_snapshot (evse_id, content_hash, record, run_id)
                        VALUES (:evse_id, :content_hash, :record, :run_id)
                        ON CONFLICT (evse_id, content_hash) DO NOTHING
                        """
                    ),
                    {
                        "evse_id": evse_id,
                        "content_hash": content_hash,
                        "record": json.dumps(record, ensure_ascii=False),
                        "run_id": str(ctx.run_id),
                    },
                )
                written += result.rowcount

        ctx.rows_written = written
        ctx.duplicate_count = len(records) - written


if __name__ == "__main__":
    run()
