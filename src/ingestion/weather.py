"""Загрузчик почасовых погодных данных (Open-Meteo Historical Weather API)
по опорным точкам 26 кантонов Швейцарии.

Для каждого кантона загружается период от последнего загруженного часа до текущей
даты за вычетом задержки публикации. Ошибка по одному кантону не останавливает
загрузку остальных — итоговый статус запуска "partial". Идемпотентность —
(canton_code, hour_ts), вставка с обновлением.
"""

import json
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text

from src.atomic_write import atomic_write_text
from src.config import CONFIG, RAW_DATA_DIR
from src.db import engine
from src.http_client import make_session
from src.run_log import start_run

SOURCE = "weather"


def _last_loaded_date(canton_code: str) -> date | None:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT max(hour_ts) FROM raw.weather_hourly WHERE canton_code = :c"
            ),
            {"c": canton_code},
        ).first()
        return row[0].date() if row and row[0] else None


def run() -> None:
    weather_cfg = CONFIG["sources"]["weather"]
    cantons = CONFIG["canton_reference_points"]
    delay_days = weather_cfg.get("publication_delay_days", 3)
    backfill_start = date.fromisoformat(weather_cfg["backfill_start_date"])
    end_date = date.today() - timedelta(days=delay_days)

    with start_run(SOURCE, {"end_date": end_date.isoformat()}) as ctx:
        session = make_session()
        total_received = 0
        total_written = 0
        errors = []

        for code, point in cantons.items():
            start_date = _last_loaded_date(code)
            start_date = (start_date + timedelta(days=1)) if start_date else backfill_start
            if start_date > end_date:
                continue

            try:
                params = {
                    "latitude": point["lat"],
                    "longitude": point["lon"],
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "hourly": ",".join(weather_cfg["hourly_variables"]),
                    "timezone": "UTC",
                }
                response = session.get(weather_cfg["archive_base_url"], params=params, timeout=60)
                response.raise_for_status()
                payload = response.json()

                now = datetime.now(timezone.utc)
                raw_path = (
                    RAW_DATA_DIR / "weather" / code / f"{now.strftime('%Y%m%dT%H%M%SZ')}.json"
                )
                atomic_write_text(raw_path, json.dumps(payload, ensure_ascii=False))

                hourly = payload.get("hourly", {})
                times = hourly.get("time", [])
                total_received += len(times)

                with engine.begin() as conn:
                    for i, ts in enumerate(times):
                        hour_ts = datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
                        conn.execute(
                            text(
                                """
                                INSERT INTO raw.weather_hourly (
                                    canton_code, hour_ts, temperature_2m, precipitation,
                                    snowfall, wind_speed_10m, run_id
                                ) VALUES (
                                    :canton_code, :hour_ts, :temperature_2m, :precipitation,
                                    :snowfall, :wind_speed_10m, :run_id
                                )
                                ON CONFLICT (canton_code, hour_ts) DO UPDATE SET
                                    temperature_2m = EXCLUDED.temperature_2m,
                                    precipitation = EXCLUDED.precipitation,
                                    snowfall = EXCLUDED.snowfall,
                                    wind_speed_10m = EXCLUDED.wind_speed_10m,
                                    run_id = EXCLUDED.run_id,
                                    ingested_at = now()
                                """
                            ),
                            {
                                "canton_code": code,
                                "hour_ts": hour_ts,
                                "temperature_2m": hourly.get("temperature_2m", [None] * len(times))[i],
                                "precipitation": hourly.get("precipitation", [None] * len(times))[i],
                                "snowfall": hourly.get("snowfall", [None] * len(times))[i],
                                "wind_speed_10m": hourly.get("wind_speed_10m", [None] * len(times))[i],
                                "run_id": str(ctx.run_id),
                            },
                        )
                total_written += len(times)
            except Exception as exc:
                errors.append(f"{code}: {exc}")

        ctx.rows_received = total_received
        ctx.rows_written = total_written
        if errors:
            ctx.status = "partial"
            ctx.error_text = "; ".join(errors)


if __name__ == "__main__":
    run()
