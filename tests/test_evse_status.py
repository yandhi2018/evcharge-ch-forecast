from datetime import datetime, timezone

from src.ingestion.evse_status import current_slot


def test_current_slot_floors_to_15_minutes():
    now = datetime(2026, 9, 16, 8, 47, 12, tzinfo=timezone.utc)
    assert current_slot(now) == datetime(2026, 9, 16, 8, 45, 0, tzinfo=timezone.utc)


def test_current_slot_exact_boundary():
    now = datetime(2026, 9, 16, 8, 30, 0, tzinfo=timezone.utc)
    assert current_slot(now) == now
