from datetime import timedelta

import pytest
from django.utils import timezone

from apps.maintenance.models import CloseReason
from apps.maintenance.services import (
    add_remark,
    close_complaint,
    complete_work_order,
    lodge_complaint,
    open_work_order,
    start_repair,
)
from apps.reports import metrics

pytestmark = pytest.mark.django_db

NOW = None  # set per-test via timezone.now()


def _backdate(obj, **fields):
    """Seed/test helper: bypass auto_now_add/append-only via queryset update."""
    type(obj).objects.filter(pk=obj.pk).update(**fields)
    obj.refresh_from_db()


def test_downtime_full_cycle_inside_window(make_equipment, staff_user, engineer, fault):
    now = timezone.now()
    eq = make_equipment(serial_number="SN-MRI", name="MRI", is_critical_asset=True)
    complaint = lodge_complaint(staff_user, eq, "coil fault")
    _backdate(complaint, created_at=now - timedelta(days=10))
    wo = start_repair(open_work_order(eq, engineer), engineer)
    wo = complete_work_order(wo, engineer, fault("electrical"))
    _backdate(wo, repair_completed_at=now - timedelta(days=8))
    result = metrics.critical_downtime_by_department(now - timedelta(days=30), now)
    assert result == {"ICU": pytest.approx(48.0, abs=0.1)}


def test_downtime_clipped_to_window(make_equipment, staff_user, engineer, fault):
    now = timezone.now()
    eq = make_equipment(serial_number="SN-CT", is_critical_asset=True)
    complaint = lodge_complaint(staff_user, eq, "tube fault")
    _backdate(complaint, created_at=now - timedelta(days=40))
    wo = start_repair(open_work_order(eq, engineer), engineer)
    wo = complete_work_order(wo, engineer, fault("other"))
    _backdate(wo, repair_completed_at=now - timedelta(days=29))
    result = metrics.critical_downtime_by_department(now - timedelta(days=30), now)
    assert result["ICU"] == pytest.approx(24.0, abs=0.1)


def test_non_critical_equipment_excluded(equipment, staff_user, engineer, fault):
    now = timezone.now()
    lodge_complaint(staff_user, equipment, "broken")  # equipment fixture: not critical
    wo = start_repair(open_work_order(equipment, engineer), engineer)
    complete_work_order(wo, engineer, fault("other"))
    assert (
        metrics.critical_downtime_by_department(
            now - timedelta(days=30), timezone.now()
        )
        == {}
    )


def test_fault_categories_and_counts(equipment, engineer, fault):
    now = timezone.now()
    wo = start_repair(open_work_order(equipment, engineer), engineer)
    complete_work_order(wo, engineer, fault("accessory_probe"))
    counts = metrics.fault_category_counts(now - timedelta(days=1), timezone.now())
    assert counts == {"Accessory / Probe / Battery": 1}
    assert metrics.repairs_completed_count(now - timedelta(days=1), timezone.now()) == 1


def test_delayed_repairs_listed(equipment, engineer):
    now = timezone.now()
    wo = start_repair(open_work_order(equipment, engineer), engineer)
    add_remark(wo, engineer, "waiting for vendor part", kind="delay")
    rows = metrics.delayed_repairs(now - timedelta(days=1), timezone.now())
    assert len(rows) == 1
    assert rows[0]["wo_id"] == wo.pk
    assert "vendor part" in rows[0]["latest_delay_note"]


def test_resolved_credits_all_participants(
    equipment, staff_user, engineer, engineer2, fault
):
    from apps.maintenance.services import (
        complete_work_order,
        lodge_complaint,
        open_work_order,
        start_repair,
    )

    now = timezone.now()
    lodge_complaint(staff_user, equipment, "no power")
    wo = start_repair(open_work_order(equipment, engineer), engineer)
    complete_work_order(
        wo, engineer2, fault_category=fault("mechanical"), participants=[engineer]
    )
    rows = {
        r["employee_id"]: r
        for r in metrics.per_engineer_resolved(now - timedelta(days=1), timezone.now())
    }
    assert rows["EMP-100"]["resolved_count"] == 1  # participant
    assert rows["EMP-101"]["resolved_count"] == 1  # completer, auto-participant


def test_resolved_credits_closer_for_duplicate(equipment, staff_user, engineer):
    from apps.maintenance.services import lodge_complaint

    now = timezone.now()
    first = lodge_complaint(staff_user, equipment, "broken")
    dup = lodge_complaint(staff_user, equipment, "also broken")
    close_complaint(
        dup, engineer, CloseReason.DUPLICATE, duplicate_of=first, close_note="dup"
    )
    rows = {
        r["employee_id"]: r
        for r in metrics.per_engineer_resolved(now - timedelta(days=1), timezone.now())
    }
    assert rows["EMP-100"]["resolved_count"] == 1


def test_drilldown_lists_equipment_and_remarks(equipment, staff_user, engineer, fault):
    from apps.maintenance.services import (
        add_remark,
        complete_work_order,
        lodge_complaint,
        open_work_order,
        start_repair,
    )

    now = timezone.now()
    lodge_complaint(staff_user, equipment, "no power")
    wo = start_repair(open_work_order(equipment, engineer), engineer)
    add_remark(wo, engineer, "ordered parts, installed, verified")
    complete_work_order(wo, engineer, fault_category=fault("electrical"))
    rows = metrics.resolved_complaints_for_engineer(
        engineer, now - timedelta(days=1), timezone.now()
    )
    assert len(rows) == 1
    assert rows[0]["equipment_serial"] == "SN-0001"
    assert rows[0]["resolution_type"] == "Repaired"
    assert any("ordered parts" in r for r in rows[0]["remarks"])


def test_condemned_complaints_excluded_from_resolved(equipment, staff_user, engineer):
    from apps.equipment.services import condemn_equipment
    from apps.maintenance.services import lodge_complaint

    now = timezone.now()
    lodge_complaint(staff_user, equipment, "broken")
    condemn_equipment(
        equipment, engineer, remark="beyond repair", condemned_location="store"
    )
    # condemnation is not a "resolved" complaint — nobody is credited
    assert metrics.per_engineer_resolved(now - timedelta(days=1), timezone.now()) == []
    assert (
        metrics.resolved_complaints_for_engineer(
            engineer, now - timedelta(days=1), timezone.now()
        )
        == []
    )


def test_recent_confirmations_lists_not_functional(
    equipment, staff_user, engineer, fault
):
    from apps.maintenance.services import (
        complete_work_order,
        confirm_complaint,
        lodge_complaint,
        open_work_order,
        start_repair,
    )

    now = timezone.now()
    complaint = lodge_complaint(staff_user, equipment, "no power")
    wo = start_repair(open_work_order(equipment, engineer), engineer)
    complete_work_order(wo, engineer, fault_category=fault("electrical"))
    complaint.refresh_from_db()
    confirm_complaint(complaint, staff_user, is_functional=False)
    rows = metrics.recent_confirmations(now - timedelta(days=1), timezone.now())
    assert len(rows) == 1
    assert rows[0]["is_functional"] is False
    assert rows[0]["work_order_id"] == wo.pk
