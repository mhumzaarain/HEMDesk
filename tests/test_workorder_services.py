import pytest
from django.core.exceptions import PermissionDenied

from apps.core.exceptions import WorkOrderStateError
from apps.equipment.models import EquipmentStatus
from apps.maintenance.models import (
    CloseReason,
    ComplaintStatus,
    RemarkKind,
    WorkOrderOutcome,
    WorkOrderStatus,
)
from apps.maintenance.services import (
    add_participant,
    add_remark,
    cancel_work_order,
    complete_work_order,
    lodge_complaint,
    open_work_order,
    start_repair,
)

pytestmark = pytest.mark.django_db


def test_open_work_order_attaches_all_open_complaints(equipment, staff_user, engineer):
    c1 = lodge_complaint(staff_user, equipment, "broken")
    c2 = lodge_complaint(staff_user, equipment, "also broken")
    wo = open_work_order(equipment, engineer)
    c1.refresh_from_db()
    c2.refresh_from_db()
    assert c1.status == ComplaintStatus.ATTACHED and c1.work_order == wo
    assert c2.status == ComplaintStatus.ATTACHED and c2.work_order == wo


def test_cannot_open_second_active_work_order(equipment, engineer):
    open_work_order(equipment, engineer)
    with pytest.raises(WorkOrderStateError):
        open_work_order(equipment, engineer)


def test_start_repair_flow(equipment, engineer):
    wo = open_work_order(equipment, engineer)
    wo = start_repair(wo, engineer)
    equipment.refresh_from_db()
    assert wo.status == WorkOrderStatus.IN_PROGRESS
    assert wo.repair_started_at is not None
    assert engineer in wo.participants.all()
    assert equipment.status == EquipmentStatus.IN_REPAIR
    event = equipment.status_events.first()
    assert event.work_order == wo


def test_cannot_start_twice(equipment, engineer):
    wo = start_repair(open_work_order(equipment, engineer), engineer)
    with pytest.raises(WorkOrderStateError):
        start_repair(wo, engineer)


def test_complete_requires_fault_category(equipment, engineer):
    wo = start_repair(open_work_order(equipment, engineer), engineer)
    with pytest.raises(ValueError):
        complete_work_order(wo, engineer, fault_category="")
    with pytest.raises(ValueError):
        complete_work_order(wo, engineer, fault_category="bogus")


def test_complete_work_order_full_cascade(
    equipment, staff_user, engineer, engineer2, fault
):
    complaint = lodge_complaint(staff_user, equipment, "no power")
    wo = start_repair(open_work_order(equipment, engineer), engineer)
    wo = complete_work_order(
        wo,
        engineer2,
        fault_category=fault("accessory_probe"),
        participants=[engineer],
        remark="replaced battery pack",
    )
    equipment.refresh_from_db()
    complaint.refresh_from_db()
    assert wo.status == WorkOrderStatus.COMPLETED
    assert wo.outcome == WorkOrderOutcome.REPAIRED
    assert wo.fault_category == fault("accessory_probe")
    assert wo.repair_completed_at is not None
    assert wo.closed_by == engineer2
    assert set(wo.participants.all()) == {engineer, engineer2}
    assert equipment.status == EquipmentStatus.WORKING
    assert complaint.status == ComplaintStatus.CLOSED
    assert complaint.close_reason == CloseReason.RESOLVED
    assert wo.remarks.filter(text="replaced battery pack").exists()


def test_cannot_complete_unstarted_work_order(equipment, engineer, fault):
    wo = open_work_order(equipment, engineer)
    with pytest.raises(WorkOrderStateError):
        complete_work_order(wo, engineer, fault_category=fault("other"))


def test_cancel_from_in_progress_restores_working(equipment, staff_user, engineer):
    complaint = lodge_complaint(staff_user, equipment, "weird noise")
    wo = start_repair(open_work_order(equipment, engineer), engineer)
    wo = cancel_work_order(wo, engineer, note="no fault found on inspection")
    equipment.refresh_from_db()
    complaint.refresh_from_db()
    assert wo.status == WorkOrderStatus.CANCELLED
    assert equipment.status == EquipmentStatus.WORKING
    assert complaint.close_reason == CloseReason.NO_FAULT
    assert wo.remarks.filter(kind=RemarkKind.SYSTEM).exists()


def test_staff_cannot_touch_work_orders(equipment, staff_user, engineer):
    wo = open_work_order(equipment, engineer)
    for call in (
        lambda: start_repair(wo, staff_user),
        lambda: add_remark(wo, staff_user, "hello"),
        lambda: add_participant(wo, engineer, staff_user),
    ):
        with pytest.raises(PermissionDenied):
            call()


def test_add_remark_and_participant(equipment, engineer, engineer2):
    wo = open_work_order(equipment, engineer)
    remark = add_remark(wo, engineer, "waiting for vendor part", kind=RemarkKind.DELAY)
    assert remark.kind == RemarkKind.DELAY
    add_participant(wo, engineer, engineer2)
    assert engineer2 in wo.participants.all()
