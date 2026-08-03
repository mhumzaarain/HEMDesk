from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import Roles
from apps.core.exceptions import DomainError
from apps.equipment.models import Department, Equipment, EquipmentStatus

from . import services
from .forms import (
    CloseComplaintForm,
    ComplaintForm,
    CompleteWorkOrderForm,
    PPMCompleteForm,
    PPMScheduleForm,
    RemarkForm,
)
from .models import (
    PPM_DUE_SOON_DAYS,
    Complaint,
    ComplaintStatus,
    PPMSchedule,
    WorkOrder,
)

ENGINEER_ROLES = (Roles.ENGINEER, Roles.ADMIN)


def _require_engineer(user):
    if user.role not in ENGINEER_ROLES:
        raise PermissionDenied


@login_required
def complaint_new(request):
    form = ComplaintForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            complaint = services.lodge_complaint(
                request.user,
                form.cleaned_data["equipment"],
                form.cleaned_data["description"],
            )
        except DomainError as exc:
            messages.error(request, str(exc))
            return redirect("complaint_new")
        messages.success(request, f"Complaint #{complaint.pk} lodged. Thank you.")
        return redirect("my_complaints")
    return render(request, "maintenance/complaint_form.html", {"form": form})


@login_required
def my_complaints(request):
    complaints = Complaint.objects.filter(reporter=request.user).select_related(
        "equipment", "work_order"
    )
    pending = sum(1 for c in complaints if c.is_awaiting_confirmation)
    return render(
        request,
        "maintenance/my_complaints.html",
        {"complaints": complaints, "pending_confirmations": pending},
    )


@login_required
@require_POST
def complaint_confirm(request, pk):
    complaint = get_object_or_404(Complaint, pk=pk)
    is_functional = request.POST.get("functional") == "yes"
    try:
        services.confirm_complaint(complaint, request.user, is_functional)
    except (DomainError, PermissionDenied) as exc:
        if isinstance(exc, PermissionDenied):
            raise
        messages.error(request, str(exc))
    else:
        messages.success(request, "Thank you — your response was recorded.")
    return redirect("my_complaints")


def _open_complaints_queryset(request):
    qs = (
        Complaint.objects.filter(
            status__in=[ComplaintStatus.OPEN, ComplaintStatus.ATTACHED]
        )
        .select_related("equipment__department", "reporter", "work_order")
        .order_by("-created_at")
    )
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(equipment__name__icontains=q)
            | Q(equipment__serial_number__icontains=q)
            | Q(description__icontains=q)
            | Q(reporter__username__icontains=q)
            | Q(reporter__first_name__icontains=q)
            | Q(reporter__last_name__icontains=q)
        )
    state = request.GET.get("state", "")
    if state == "unassigned":
        qs = qs.filter(work_order__isnull=True)
    elif state == "assigned":
        qs = qs.filter(work_order__isnull=False)
    return qs


@login_required
def complaint_queue(request):
    _require_engineer(request.user)
    return render(
        request,
        "maintenance/queue.html",
        {"complaints": _open_complaints_queryset(request)},
    )


@login_required
def complaint_queue_rows(request):
    _require_engineer(request.user)
    return render(
        request,
        "maintenance/_queue_rows.html",
        {"complaints": _open_complaints_queryset(request)},
    )


@login_required
def complaint_close(request, pk):
    _require_engineer(request.user)
    complaint = get_object_or_404(Complaint, pk=pk)
    form = CloseComplaintForm(request.POST or None, complaint=complaint)
    if request.method == "POST" and form.is_valid():
        try:
            services.close_complaint(
                complaint,
                request.user,
                form.cleaned_data["close_reason"],
                duplicate_of=form.cleaned_data["duplicate_of"],
                close_note=form.cleaned_data["close_note"],
            )
        except (DomainError, ValueError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"Complaint #{complaint.pk} closed.")
        return redirect("complaint_queue")
    return render(
        request,
        "maintenance/complaint_close.html",
        {"complaint": complaint, "form": form},
    )


@login_required
@require_POST
def workorder_open(request, equipment_pk):
    _require_engineer(request.user)
    equipment = get_object_or_404(Equipment, pk=equipment_pk)
    try:
        wo = services.open_work_order(equipment, request.user)
    except DomainError as exc:
        messages.error(request, str(exc))
        return redirect("equipment_detail", pk=equipment_pk)
    messages.success(request, f"Work Order #{wo.pk} opened.")
    return redirect("workorder_detail", pk=wo.pk)


@login_required
def workorder_detail(request, pk):
    _require_engineer(request.user)
    wo = get_object_or_404(
        WorkOrder.objects.select_related(
            "equipment__department", "opened_by"
        ).prefetch_related("remarks__author", "participants", "complaints__reporter"),
        pk=pk,
    )
    return render(
        request,
        "maintenance/workorder_detail.html",
        {
            "wo": wo,
            "remark_form": RemarkForm(),
            "can_engineer": request.user.is_engineer_or_admin,
        },
    )


@login_required
@require_POST
def workorder_start(request, pk):
    _require_engineer(request.user)
    wo = get_object_or_404(WorkOrder, pk=pk)
    try:
        services.start_repair(wo, request.user)
    except DomainError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Repair started on WO #{wo.pk}.")
    return redirect("workorder_detail", pk=pk)


@login_required
def workorder_complete(request, pk):
    _require_engineer(request.user)
    wo = get_object_or_404(WorkOrder, pk=pk)
    form = CompleteWorkOrderForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.complete_work_order(
                wo,
                request.user,
                form.cleaned_data["fault_category"],
                participants=form.cleaned_data["participants"],
                remark=form.cleaned_data["remark"],
            )
        except (DomainError, ValueError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"WO #{wo.pk} completed. Equipment is Working.")
            return redirect("workorder_detail", pk=pk)
    form.fields["participants"].initial = wo.participants.all()
    return render(
        request, "maintenance/workorder_complete.html", {"wo": wo, "form": form}
    )


@login_required
@require_POST
def workorder_cancel(request, pk):
    _require_engineer(request.user)
    wo = get_object_or_404(WorkOrder, pk=pk)
    try:
        services.cancel_work_order(wo, request.user, note=request.POST.get("note", ""))
    except DomainError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"WO #{wo.pk} cancelled (no fault found).")
    return redirect("workorder_detail", pk=pk)


@login_required
@require_POST
def workorder_remark(request, pk):
    _require_engineer(request.user)
    wo = get_object_or_404(WorkOrder, pk=pk)
    form = RemarkForm(request.POST)
    if form.is_valid():
        services.add_remark(
            wo, request.user, form.cleaned_data["text"], kind=form.cleaned_data["kind"]
        )
        messages.success(request, "Remark added.")
    return redirect("workorder_detail", pk=pk)


@login_required
@require_POST
def workorder_join(request, pk):
    _require_engineer(request.user)
    wo = get_object_or_404(WorkOrder, pk=pk)
    try:
        services.add_participant(wo, request.user, request.user)
    except DomainError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "You are now a participant on this work order.")
    return redirect("workorder_detail", pk=pk)


@login_required
def ppm_schedule_edit(request, equipment_pk):
    _require_engineer(request.user)
    equipment = get_object_or_404(Equipment, pk=equipment_pk)
    schedule = getattr(equipment, "ppm_schedule", None)
    initial = (
        {
            "interval": schedule.interval,
            "next_due": schedule.next_due,
            "active": schedule.active,
        }
        if schedule
        else None
    )
    form = PPMScheduleForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            services.set_ppm_schedule(
                equipment,
                request.user,
                form.cleaned_data["interval"],
                form.cleaned_data["next_due"],
                active=form.cleaned_data["active"],
            )
        except (DomainError, ValueError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "PPM schedule saved.")
        return redirect("equipment_detail", pk=equipment_pk)
    return render(
        request,
        "maintenance/ppm_schedule_form.html",
        {"equipment": equipment, "form": form, "schedule": schedule},
    )


@login_required
def ppm_complete(request, schedule_pk):
    _require_engineer(request.user)
    schedule = get_object_or_404(
        PPMSchedule.objects.select_related("equipment"), pk=schedule_pk
    )
    form = PPMCompleteForm(
        request.POST or None, initial={"performed_at": timezone.localdate()}
    )
    if request.method == "POST" and form.is_valid():
        try:
            services.complete_ppm(
                schedule,
                request.user,
                form.cleaned_data["outcome"],
                form.cleaned_data["performed_at"],
                engineers=form.cleaned_data["engineers"],
                remarks=form.cleaned_data["remarks"],
                open_wo=form.cleaned_data["open_work_order"],
            )
        except (DomainError, ValueError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "PPM recorded.")
        return redirect("equipment_detail", pk=schedule.equipment_id)
    return render(
        request,
        "maintenance/ppm_complete.html",
        {"schedule": schedule, "form": form},
    )


@login_required
def ppm_due_list(request):
    _require_engineer(request.user)
    today = timezone.localdate()
    qs = (
        PPMSchedule.objects.filter(active=True)
        .exclude(equipment__status=EquipmentStatus.CONDEMNED)
        .select_related("equipment__department")
        .order_by("next_due")
    )
    selected_department = request.GET.get("department", "")
    if selected_department:
        qs = qs.filter(equipment__department_id=selected_department)
    unscheduled_count = (
        Equipment.objects.exclude(status=EquipmentStatus.CONDEMNED)
        .filter(Q(ppm_schedule__isnull=True) | Q(ppm_schedule__active=False))
        .count()
    )
    return render(
        request,
        "maintenance/ppm_due_list.html",
        {
            "overdue": qs.filter(next_due__lt=today),
            "due_soon": qs.filter(
                next_due__gte=today,
                next_due__lte=today + timedelta(days=PPM_DUE_SOON_DAYS),
            ),
            "departments": Department.objects.all(),
            "selected_department": selected_department,
            "unscheduled_count": unscheduled_count,
        },
    )
