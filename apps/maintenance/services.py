from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.core import audit
from apps.core.exceptions import ComplaintNotAllowed, WorkOrderStateError
from apps.equipment.models import EquipmentStatus
from apps.equipment.services import _require_engineer_or_admin, transition_status

from .models import (
    ACTIVE_WORKORDER_STATUSES,
    CloseReason,
    Complaint,
    ComplaintStatus,
    FaultCategory,
    FunctionalConfirmation,
    PPMInterval,
    PPMOutcome,
    PPMRecord,
    PPMSchedule,
    Remark,
    RemarkKind,
    WorkOrder,
    WorkOrderOutcome,
    WorkOrderStatus,
    add_months,
)


@transaction.atomic
def lodge_complaint(reporter, equipment, description) -> Complaint:
    equipment.refresh_from_db()
    if equipment.status == EquipmentStatus.CONDEMNED:
        raise ComplaintNotAllowed("This equipment is condemned; complaints are closed.")
    if equipment.status == EquipmentStatus.IN_REPAIR:
        active = equipment.work_orders.filter(
            status__in=ACTIVE_WORKORDER_STATUSES
        ).first()
        wo_ref = f"Work Order #{active.pk}" if active else "a work order"
        raise ComplaintNotAllowed(f"This equipment is already under repair ({wo_ref}).")
    open_wo = equipment.work_orders.filter(status=WorkOrderStatus.OPEN).first()
    complaint = Complaint.objects.create(
        equipment=equipment,
        reporter=reporter,
        description=description,
        status=ComplaintStatus.ATTACHED if open_wo else ComplaintStatus.OPEN,
        work_order=open_wo,
    )
    audit.record(
        reporter,
        "complaint.lodged",
        complaint,
        {
            "equipment": equipment.serial_number,
            "attached_to": open_wo.pk if open_wo else None,
        },
    )
    return complaint


@transaction.atomic
def close_complaint(
    complaint, actor, close_reason, duplicate_of=None, close_note=""
) -> Complaint:
    _require_engineer_or_admin(actor)
    if complaint.status == ComplaintStatus.CLOSED:
        raise WorkOrderStateError("This complaint is already closed.")
    if close_reason == CloseReason.DUPLICATE and not (duplicate_of or close_note):
        raise ValueError(
            "Closing as duplicate requires the original complaint or a note."
        )
    complaint.status = ComplaintStatus.CLOSED
    complaint.close_reason = close_reason
    complaint.duplicate_of = duplicate_of
    complaint.close_note = close_note
    complaint.closed_by = actor
    complaint.closed_at = timezone.now()
    complaint.save(
        update_fields=[
            "status",
            "close_reason",
            "duplicate_of",
            "close_note",
            "closed_by",
            "closed_at",
        ]
    )
    audit.record(
        actor,
        "complaint.closed",
        complaint,
        {
            "reason": close_reason,
            "duplicate_of": duplicate_of.pk if duplicate_of else None,
            "note": close_note,
        },
    )
    return complaint


@transaction.atomic
def open_work_order(equipment, actor) -> WorkOrder:
    _require_engineer_or_admin(actor)
    if equipment.status == EquipmentStatus.CONDEMNED:
        raise WorkOrderStateError("Cannot open a work order for condemned equipment.")
    if equipment.work_orders.filter(status__in=ACTIVE_WORKORDER_STATUSES).exists():
        raise WorkOrderStateError("This equipment already has an active work order.")
    wo = WorkOrder.objects.create(equipment=equipment, opened_by=actor)
    for complaint in equipment.complaints.filter(status=ComplaintStatus.OPEN):
        complaint.status = ComplaintStatus.ATTACHED
        complaint.work_order = wo
        complaint.save(update_fields=["status", "work_order"])
    audit.record(actor, "workorder.opened", wo, {"equipment": equipment.serial_number})
    return wo


@transaction.atomic
def start_repair(work_order, actor) -> WorkOrder:
    _require_engineer_or_admin(actor)
    if work_order.status != WorkOrderStatus.OPEN:
        raise WorkOrderStateError("Only an open work order can be started.")
    work_order.status = WorkOrderStatus.IN_PROGRESS
    work_order.repair_started_at = timezone.now()
    work_order.save(update_fields=["status", "repair_started_at"])
    work_order.participants.add(actor)
    transition_status(
        work_order.equipment,
        EquipmentStatus.IN_REPAIR,
        actor,
        remark=f"Repair started (WO #{work_order.pk})",
        work_order=work_order,
    )
    audit.record(actor, "workorder.started", work_order, {})
    return work_order


@transaction.atomic
def complete_work_order(
    work_order, actor, fault_category, participants=(), remark=""
) -> WorkOrder:
    _require_engineer_or_admin(actor)
    if work_order.status != WorkOrderStatus.IN_PROGRESS:
        raise WorkOrderStateError("Only an in-progress work order can be completed.")
    if fault_category not in FaultCategory.values:
        raise ValueError("A valid fault_category is required to complete a repair.")
    now = timezone.now()
    work_order.status = WorkOrderStatus.COMPLETED
    work_order.outcome = WorkOrderOutcome.REPAIRED
    work_order.fault_category = fault_category
    work_order.repair_completed_at = now
    work_order.closed_by = actor
    work_order.closed_at = now
    work_order.save(
        update_fields=[
            "status",
            "outcome",
            "fault_category",
            "repair_completed_at",
            "closed_by",
            "closed_at",
        ]
    )
    work_order.participants.add(actor, *participants)
    if remark:
        Remark.objects.create(work_order=work_order, author=actor, text=remark)
    transition_status(
        work_order.equipment,
        EquipmentStatus.WORKING,
        actor,
        remark=f"Repair completed (WO #{work_order.pk})",
        work_order=work_order,
    )
    for complaint in work_order.complaints.exclude(status=ComplaintStatus.CLOSED):
        close_complaint(
            complaint,
            actor,
            CloseReason.RESOLVED,
            close_note=f"Resolved by Work Order #{work_order.pk}",
        )
    audit.record(
        actor, "workorder.completed", work_order, {"fault_category": fault_category}
    )
    return work_order


@transaction.atomic
def cancel_work_order(work_order, actor, note="") -> WorkOrder:
    _require_engineer_or_admin(actor)
    if not work_order.is_active:
        raise WorkOrderStateError("Only an active work order can be cancelled.")
    was_in_progress = work_order.status == WorkOrderStatus.IN_PROGRESS
    now = timezone.now()
    work_order.status = WorkOrderStatus.CANCELLED
    work_order.closed_by = actor
    work_order.closed_at = now
    work_order.save(update_fields=["status", "closed_by", "closed_at"])
    Remark.objects.create(
        work_order=work_order,
        author=actor,
        kind=RemarkKind.SYSTEM,
        text=f"Work order cancelled. {note}".strip(),
    )
    if was_in_progress:
        transition_status(
            work_order.equipment,
            EquipmentStatus.WORKING,
            actor,
            remark=f"Repair cancelled (WO #{work_order.pk})",
            work_order=work_order,
        )
    for complaint in work_order.complaints.exclude(status=ComplaintStatus.CLOSED):
        close_complaint(
            complaint, actor, CloseReason.NO_FAULT, close_note=note or "No fault found."
        )
    audit.record(actor, "workorder.cancelled", work_order, {"note": note})
    return work_order


@transaction.atomic
def add_remark(work_order, author, text, kind=RemarkKind.NOTE) -> Remark:
    _require_engineer_or_admin(author)
    remark = Remark.objects.create(
        work_order=work_order, author=author, text=text, kind=kind
    )
    audit.record(
        author, "workorder.remark_added", work_order, {"kind": kind, "text": text}
    )
    return remark


@transaction.atomic
def add_participant(work_order, actor, user) -> None:
    _require_engineer_or_admin(actor)
    _require_engineer_or_admin(user)
    if not work_order.is_active:
        raise WorkOrderStateError("Cannot add participants to a closed work order.")
    work_order.participants.add(user)
    audit.record(
        actor, "workorder.participant_added", work_order, {"user": user.employee_id}
    )


@transaction.atomic
def confirm_complaint(complaint, actor, is_functional) -> Complaint:
    if complaint.reporter_id != actor.id:
        raise PermissionDenied("Only the reporter can confirm this complaint.")
    if not complaint.is_awaiting_confirmation:
        raise WorkOrderStateError("This complaint is not awaiting confirmation.")
    complaint.functional_confirmation = (
        FunctionalConfirmation.FUNCTIONAL
        if is_functional
        else FunctionalConfirmation.NOT_FUNCTIONAL
    )
    complaint.confirmed_at = timezone.now()
    complaint.save(update_fields=["functional_confirmation", "confirmed_at"])
    audit.record(actor, "complaint.confirmed", complaint, {"functional": is_functional})
    return complaint


@transaction.atomic
def set_ppm_schedule(equipment, actor, interval, next_due, active=True) -> PPMSchedule:
    _require_engineer_or_admin(actor)
    equipment.refresh_from_db()
    if equipment.status == EquipmentStatus.CONDEMNED:
        raise WorkOrderStateError("Cannot schedule PPM for condemned equipment.")
    if interval not in PPMInterval.values:
        raise ValueError("A valid PPM interval is required.")
    schedule, _created = PPMSchedule.objects.update_or_create(
        equipment=equipment,
        defaults={"interval": interval, "next_due": next_due, "active": active},
    )
    audit.record(
        actor,
        "ppm.schedule_set",
        schedule,
        {"interval": interval, "next_due": str(next_due), "active": active},
    )
    return schedule


@transaction.atomic
def complete_ppm(
    schedule, actor, outcome, performed_at, engineers=(), remarks="", open_wo=False
) -> PPMRecord:
    _require_engineer_or_admin(actor)
    if not schedule.active:
        raise WorkOrderStateError("This PPM schedule is inactive.")
    equipment = schedule.equipment
    equipment.refresh_from_db()
    if equipment.status == EquipmentStatus.CONDEMNED:
        raise WorkOrderStateError("This equipment is condemned.")
    if outcome not in PPMOutcome.values:
        raise ValueError("A valid PPM outcome is required.")
    if performed_at > timezone.localdate():
        raise ValueError("The performed date cannot be in the future.")
    if open_wo and outcome != PPMOutcome.FAILED:
        raise ValueError("A work order can only be opened for a failed PPM.")
    active_wo = equipment.work_orders.filter(
        status__in=ACTIVE_WORKORDER_STATUSES
    ).first()
    if active_wo:
        raise WorkOrderStateError(
            f"This equipment is under repair (WO #{active_wo.pk}) — "
            "complete or cancel it first."
        )
    for engineer in engineers:
        _require_engineer_or_admin(engineer)
    work_order = open_work_order(equipment, actor) if open_wo else None
    record = PPMRecord.objects.create(
        schedule=schedule,
        due_date=schedule.next_due,
        performed_at=performed_at,
        outcome=outcome,
        remarks=remarks,
        recorded_by=actor,
        work_order=work_order,
    )
    record.engineers.add(actor, *engineers)
    schedule.next_due = add_months(performed_at, schedule.interval_months)
    schedule.save(update_fields=["next_due"])
    audit.record(
        actor,
        "ppm.completed",
        record,
        {
            "outcome": outcome,
            "performed_at": str(performed_at),
            "work_order": work_order.pk if work_order else None,
        },
    )
    return record
