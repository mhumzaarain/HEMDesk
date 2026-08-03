from datetime import date

import pytest

from apps.maintenance.models import (
    PPMInterval,
    PPMOutcome,
    PPMRecord,
    PPMSchedule,
    add_months,
)


def test_add_months_simple():
    assert add_months(date(2026, 1, 15), 1) == date(2026, 2, 15)
    assert add_months(date(2026, 3, 10), 3) == date(2026, 6, 10)


def test_add_months_clamps_to_month_end():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)  # leap year
    assert add_months(date(2026, 8, 31), 1) == date(2026, 9, 30)


def test_add_months_year_rollover():
    assert add_months(date(2026, 11, 5), 3) == date(2027, 2, 5)
    assert add_months(date(2026, 6, 1), 12) == date(2027, 6, 1)


@pytest.fixture
def schedule(equipment):
    return PPMSchedule.objects.create(
        equipment=equipment,
        interval=PPMInterval.QUARTERLY,
        next_due=date(2026, 9, 1),
    )


def test_schedule_defaults_and_interval_months(schedule):
    assert schedule.active is True
    assert schedule.interval_months == 3


def test_schedule_cannot_be_deleted(schedule):
    with pytest.raises(TypeError):
        schedule.delete()


def test_record_is_append_only(schedule, engineer):
    record = PPMRecord.objects.create(
        schedule=schedule,
        due_date=schedule.next_due,
        performed_at=date(2026, 8, 1),
        outcome=PPMOutcome.PASSED,
        recorded_by=engineer,
    )
    record.remarks = "edited"
    with pytest.raises(TypeError):
        record.save()
