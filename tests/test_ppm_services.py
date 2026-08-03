from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.core.exceptions import WorkOrderStateError
from apps.core.models import AuditLog
from apps.equipment.models import EquipmentStatus
from apps.maintenance import services
from apps.maintenance.models import (
    PPMInterval,
    PPMOutcome,
    PPMRecord,
    PPMSchedule,
    WorkOrderStatus,
    add_months,
)


@pytest.fixture
def schedule(equipment, engineer):
    return services.set_ppm_schedule(
        equipment, engineer, PPMInterval.QUARTERLY, timezone.localdate()
    )


class TestSetPPMSchedule:
    def test_creates_schedule_with_audit(self, equipment, engineer):
        due = timezone.localdate() + timedelta(days=10)
        schedule = services.set_ppm_schedule(
            equipment, engineer, PPMInterval.MONTHLY, due
        )
        assert schedule.interval == PPMInterval.MONTHLY
        assert schedule.next_due == due
        assert schedule.active is True
        log = AuditLog.objects.get(verb="ppm.schedule_set")
        assert log.actor == engineer
        assert log.object_id == str(schedule.pk)

    def test_updates_existing_schedule_in_place(self, schedule, engineer):
        due = timezone.localdate() + timedelta(days=5)
        updated = services.set_ppm_schedule(
            schedule.equipment, engineer, PPMInterval.ANNUAL, due, active=False
        )
        assert updated.pk == schedule.pk
        assert updated.interval == PPMInterval.ANNUAL
        assert updated.active is False
        assert PPMSchedule.objects.count() == 1

    def test_staff_cannot_set_schedule(self, equipment, staff_user):
        with pytest.raises(PermissionDenied):
            services.set_ppm_schedule(
                equipment, staff_user, PPMInterval.MONTHLY, timezone.localdate()
            )

    def test_rejects_condemned_equipment(self, equipment, engineer):
        equipment.status = EquipmentStatus.CONDEMNED
        equipment.save(update_fields=["status"])
        with pytest.raises(WorkOrderStateError):
            services.set_ppm_schedule(
                equipment, engineer, PPMInterval.MONTHLY, timezone.localdate()
            )

    def test_rejects_bad_interval(self, equipment, engineer):
        with pytest.raises(ValueError):
            services.set_ppm_schedule(
                equipment, engineer, "weekly", timezone.localdate()
            )


class TestCompletePPM:
    def test_records_and_advances_next_due(self, schedule, engineer):
        performed = timezone.localdate() - timedelta(days=2)
        old_due = schedule.next_due
        record = services.complete_ppm(
            schedule, engineer, PPMOutcome.PASSED, performed, remarks="All good."
        )
        schedule.refresh_from_db()
        assert record.due_date == old_due
        assert record.performed_at == performed
        assert record.work_order is None
        assert engineer in record.engineers.all()
        # quarterly: +3 months from the performed date, not from old_due
        assert schedule.next_due == add_months(performed, 3)
        assert schedule.next_due != add_months(old_due, 3) or performed == old_due
        log = AuditLog.objects.get(verb="ppm.completed")
        assert log.actor == engineer

    def test_extra_engineers_are_recorded(self, schedule, engineer, engineer2):
        record = services.complete_ppm(
            schedule,
            engineer,
            PPMOutcome.PASSED,
            timezone.localdate(),
            engineers=[engineer2],
        )
        assert set(record.engineers.all()) == {engineer, engineer2}

    def test_rejects_future_performed_at(self, schedule, engineer):
        with pytest.raises(ValueError):
            services.complete_ppm(
                schedule,
                engineer,
                PPMOutcome.PASSED,
                timezone.localdate() + timedelta(days=1),
            )

    def test_rejects_inactive_schedule(self, schedule, engineer):
        PPMSchedule.objects.filter(pk=schedule.pk).update(active=False)
        schedule.refresh_from_db()
        with pytest.raises(WorkOrderStateError):
            services.complete_ppm(
                schedule, engineer, PPMOutcome.PASSED, timezone.localdate()
            )

    def test_rejects_bad_outcome(self, schedule, engineer):
        with pytest.raises(ValueError):
            services.complete_ppm(schedule, engineer, "ok", timezone.localdate())

    def test_staff_cannot_complete(self, schedule, staff_user):
        with pytest.raises(PermissionDenied):
            services.complete_ppm(
                schedule, staff_user, PPMOutcome.PASSED, timezone.localdate()
            )

    def test_blocked_while_work_order_active(self, schedule, engineer):
        wo = services.open_work_order(schedule.equipment, engineer)
        with pytest.raises(WorkOrderStateError) as exc:
            services.complete_ppm(
                schedule, engineer, PPMOutcome.PASSED, timezone.localdate()
            )
        assert f"WO #{wo.pk}" in str(exc.value)
        assert PPMRecord.objects.count() == 0

    def test_open_wo_requires_failed_outcome(self, schedule, engineer):
        with pytest.raises(ValueError):
            services.complete_ppm(
                schedule,
                engineer,
                PPMOutcome.PASSED,
                timezone.localdate(),
                open_wo=True,
            )

    def test_failed_with_open_wo_creates_linked_work_order(self, schedule, engineer):
        record = services.complete_ppm(
            schedule,
            engineer,
            PPMOutcome.FAILED,
            timezone.localdate(),
            open_wo=True,
            remarks="Leakage current above limit.",
        )
        assert record.work_order is not None
        assert record.work_order.status == WorkOrderStatus.OPEN
        assert record.work_order.equipment == schedule.equipment

    def test_failed_without_open_wo_records_only(self, schedule, engineer):
        record = services.complete_ppm(
            schedule, engineer, PPMOutcome.FAILED, timezone.localdate()
        )
        assert record.work_order is None

    def test_rejects_non_engineer_extra_engineer(self, schedule, engineer, staff_user):
        with pytest.raises(PermissionDenied):
            services.complete_ppm(
                schedule,
                engineer,
                PPMOutcome.PASSED,
                timezone.localdate(),
                engineers=[staff_user],
            )
        assert PPMRecord.objects.count() == 0
