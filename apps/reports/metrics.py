"""Dashboard/report numbers. Numbers come from SQL/ORM — never from an LLM.
No MTTR and no SLA metrics anywhere (spec sections 7 and 9)."""

from collections import defaultdict
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from apps.equipment.models import (
    AccessoryEvent,
    AccessoryEventKind,
    Equipment,
    EquipmentStatus,
)
from apps.maintenance.models import (
    PPM_DUE_SOON_DAYS,
    CloseReason,
    Complaint,
    ComplaintStatus,
    FunctionalConfirmation,
    PPMSchedule,
    Remark,
    RemarkKind,
    WorkOrder,
    WorkOrderOutcome,
    WorkOrderStatus,
)


def _downtime_start(wo):
    first = min((c.created_at for c in wo.complaints.all()), default=None)
    return first or wo.opened_at


def _overlap_hours(start, end, window_start, window_end):
    lo, hi = max(start, window_start), min(end, window_end)
    return max((hi - lo).total_seconds() / 3600.0, 0.0)


def critical_downtime_by_department(window_start, window_end):
    totals = defaultdict(float)
    work_orders = (
        WorkOrder.objects.filter(equipment__is_critical_asset=True)
        .exclude(status=WorkOrderStatus.CANCELLED)
        .select_related("equipment__department")
        .prefetch_related("complaints")
    )
    for wo in work_orders:
        down_from = _downtime_start(wo)
        down_to = wo.repair_completed_at or window_end
        hours = _overlap_hours(down_from, down_to, window_start, window_end)
        if hours > 0:
            totals[wo.equipment.department.name] += hours
    return dict(totals)


def complaints_per_department(window_start, window_end):
    rows = (
        Complaint.objects.filter(created_at__range=(window_start, window_end))
        .values("equipment__department__name")
        .annotate(n=Count("id"))
        .order_by("-n")
    )
    return {r["equipment__department__name"]: r["n"] for r in rows}


def most_complained_devices(window_start, window_end, limit=10):
    rows = (
        Equipment.objects.annotate(
            n=Count(
                "complaints",
                filter=Q(complaints__created_at__range=(window_start, window_end)),
            )
        )
        .filter(n__gt=0)
        .order_by("-n")[:limit]
    )
    return [(f"{eq.name} ({eq.serial_number})", eq.n) for eq in rows]


def fault_category_counts(window_start, window_end):
    rows = (
        WorkOrder.objects.filter(
            status=WorkOrderStatus.COMPLETED,
            repair_completed_at__range=(window_start, window_end),
            fault_category__isnull=False,
        )
        .values("fault_category__name")
        .annotate(n=Count("id"))
        .order_by("-n")
    )
    return {r["fault_category__name"]: r["n"] for r in rows}


def repairs_completed_count(window_start, window_end):
    return WorkOrder.objects.filter(
        status=WorkOrderStatus.COMPLETED,
        repair_completed_at__range=(window_start, window_end),
    ).count()


def open_workorders_count():
    return WorkOrder.objects.filter(
        status__in=[WorkOrderStatus.OPEN, WorkOrderStatus.IN_PROGRESS]
    ).count()


def delayed_repairs(window_start, window_end):
    delay_remarks = (
        Remark.objects.filter(
            kind=RemarkKind.DELAY,
            created_at__range=(window_start, window_end),
        )
        .select_related("work_order__equipment")
        .order_by("created_at")
    )
    latest = {}
    for remark in delay_remarks:
        latest[remark.work_order_id] = remark
    return [
        {
            "wo_id": wo_id,
            "equipment": str(r.work_order.equipment),
            "latest_delay_note": r.text,
        }
        for wo_id, r in latest.items()
    ]


def resolving_engineer_ids(complaint):
    if complaint.work_order_id is not None:
        ids = {u.id for u in complaint.work_order.participants.all()}
        if ids:
            return ids
    return {complaint.closed_by_id} if complaint.closed_by_id else set()


def _resolved_complaints(window_start, window_end):
    return (
        Complaint.objects.filter(
            Q(close_reason__in=[CloseReason.DUPLICATE, CloseReason.NO_FAULT])
            | Q(
                close_reason=CloseReason.RESOLVED,
                work_order__outcome=WorkOrderOutcome.REPAIRED,
            ),
            status=ComplaintStatus.CLOSED,
            closed_at__range=(window_start, window_end),
        )
        .select_related("equipment", "work_order")
        .prefetch_related("work_order__participants", "work_order__remarks")
    )


def per_engineer_resolved(window_start, window_end):
    from apps.accounts.models import User

    counts = {}
    for complaint in _resolved_complaints(window_start, window_end):
        for uid in resolving_engineer_ids(complaint):
            counts[uid] = counts.get(uid, 0) + 1
    users = {u.id: u for u in User.objects.filter(id__in=counts)}
    rows = [
        {
            "user_id": uid,
            "name": users[uid].get_full_name() or users[uid].username,
            "employee_id": users[uid].employee_id,
            "resolved_count": n,
        }
        for uid, n in counts.items()
        if uid in users
    ]
    return sorted(rows, key=lambda r: -r["resolved_count"])


_RESOLUTION_LABEL = {
    CloseReason.RESOLVED: "Repaired",
    CloseReason.DUPLICATE: "Duplicate",
    CloseReason.NO_FAULT: "No fault",
}


def resolved_complaints_for_engineer(user, window_start, window_end):
    rows = []
    for complaint in _resolved_complaints(window_start, window_end):
        if user.id not in resolving_engineer_ids(complaint):
            continue
        if complaint.close_reason == CloseReason.RESOLVED and complaint.work_order_id:
            remarks = [r.text for r in complaint.work_order.remarks.all()]
        else:
            remarks = [complaint.close_note] if complaint.close_note else []
        eq = complaint.equipment
        rows.append(
            {
                "complaint_id": complaint.id,
                "equipment_id": eq.id,
                "equipment_name": eq.name,
                "equipment_model": eq.model_number,
                "equipment_serial": eq.serial_number,
                "resolution_type": _RESOLUTION_LABEL[complaint.close_reason],
                "resolved_at": complaint.closed_at,
                "remarks": remarks,
            }
        )
    return sorted(rows, key=lambda r: r["resolved_at"], reverse=True)


def equipment_working_percent():
    active = Equipment.objects.exclude(status=EquipmentStatus.CONDEMNED)
    total = active.count()
    if total == 0:
        return None
    working = active.filter(status=EquipmentStatus.WORKING).count()
    return round(100 * working / total)


def recent_confirmations(window_start, window_end):
    rows = (
        Complaint.objects.filter(
            functional_confirmation__isnull=False,
            confirmed_at__range=(window_start, window_end),
        )
        .select_related("equipment")
        .order_by("-confirmed_at")
    )
    return [
        {
            "complaint_id": c.id,
            "equipment": str(c.equipment),
            "work_order_id": c.work_order_id,
            "is_functional": c.functional_confirmation
            == FunctionalConfirmation.FUNCTIONAL,
            "confirmed_at": c.confirmed_at,
        }
        for c in rows
    ]


def month_metrics(month):
    """All aggregates for one calendar month, JSON-serializable (spec §3).
    `month` is the first day of the month."""
    import calendar
    from datetime import datetime, timedelta

    from django.utils import timezone as tz

    start = tz.make_aware(datetime(month.year, month.month, 1))
    last_day = calendar.monthrange(month.year, month.month)[1]
    end = tz.make_aware(datetime(month.year, month.month, last_day)) + timedelta(
        days=1
    )
    downtime = critical_downtime_by_department(start, end)
    return {
        "month": f"{month:%Y-%m}",
        "downtime_by_department": {k: round(v, 1) for k, v in downtime.items()},
        "complaints_per_department": complaints_per_department(start, end),
        "most_complained_devices": most_complained_devices(start, end),
        "fault_category_counts": fault_category_counts(start, end),
        "repairs_completed": repairs_completed_count(start, end),
        "open_workorders": open_workorders_count(),
        "delayed_repairs": delayed_repairs(start, end),
        "per_engineer_resolved": per_engineer_resolved(start, end),
    }


def _active_ppm_schedules():
    return PPMSchedule.objects.filter(active=True).exclude(
        equipment__status=EquipmentStatus.CONDEMNED
    )


def ppm_due_counts():
    today = timezone.localdate()
    qs = _active_ppm_schedules()
    return {
        "overdue": qs.filter(next_due__lt=today).count(),
        "due_soon": qs.filter(
            next_due__gte=today,
            next_due__lte=today + timedelta(days=PPM_DUE_SOON_DAYS),
        ).count(),
    }


def ppm_overdue_by_department():
    rows = (
        _active_ppm_schedules()
        .filter(next_due__lt=timezone.localdate())
        .values("equipment__department__name")
        .annotate(n=Count("id"))
        .order_by("-n")
    )
    return {r["equipment__department__name"]: r["n"] for r in rows}


def accessory_replacements_by_equipment(window_start, window_end, limit=5):
    rows = (
        AccessoryEvent.objects.filter(
            kind=AccessoryEventKind.REPLACED,
            created_at__range=(window_start, window_end),
        )
        .values("equipment_id", "equipment__name", "equipment__serial_number")
        .annotate(n=Count("id"))
        .order_by("-n")[:limit]
    )
    return [
        {
            "equipment_id": r["equipment_id"],
            "label": f"{r['equipment__name']} ({r['equipment__serial_number']})",
            "n": r["n"],
        }
        for r in rows
    ]


def accessory_replacements_by_type(window_start, window_end, limit=5):
    rows = (
        AccessoryEvent.objects.filter(
            kind=AccessoryEventKind.REPLACED,
            created_at__range=(window_start, window_end),
        )
        .values("accessory_type__name", "accessory_type__equipment_name")
        .annotate(n=Count("id"))
        .order_by("-n")[:limit]
    )
    return [
        {
            "label": (
                f"{r['accessory_type__name']} — "
                f"{r['accessory_type__equipment_name']}"
            ),
            "n": r["n"],
        }
        for r in rows
    ]
