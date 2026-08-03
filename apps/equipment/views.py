from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import DetailView, ListView, View

from apps.accounts.mixins import RoleRequiredMixin
from apps.accounts.models import Roles
from apps.core.exceptions import DomainError

from . import importer, services
from .forms import CondemnForm, EquipmentForm
from .models import Equipment, EquipmentStatus

ENGINEER_ROLES = (Roles.ENGINEER, Roles.ADMIN)
SESSION_KEY = "equipment_import"


class EquipmentListView(LoginRequiredMixin, ListView):
    model = Equipment
    template_name = "equipment/list.html"
    paginate_by = 25

    def get_template_names(self):
        if self.request.headers.get("HX-Request"):
            return ["equipment/_list_rows.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_choices"] = [("", "All")] + list(EquipmentStatus.choices)
        return ctx

    def get_queryset(self):
        qs = super().get_queryset().select_related("department")
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(serial_number__icontains=q)
                | Q(name__icontains=q)
                | Q(model_number__icontains=q)
                | Q(manufacturer__icontains=q)
            )
        status = self.request.GET.get("status", "")
        if status:
            qs = qs.filter(status=status)
        return qs


class EquipmentSearchView(LoginRequiredMixin, View):
    """HTMX partial used by list filtering and the complaint form picker."""

    def get(self, request):
        q = request.GET.get("q", "").strip()
        results = Equipment.objects.select_related("department")
        if request.GET.get("exclude_unavailable"):
            results = results.filter(status=EquipmentStatus.WORKING)
        if q:
            results = results.filter(
                Q(serial_number__icontains=q)
                | Q(name__icontains=q)
                | Q(model_number__icontains=q)
                | Q(manufacturer__icontains=q)
            )[:10]
        else:
            results = results.none()
        return render(request, "equipment/_search_results.html", {"results": results})


class EquipmentDetailView(LoginRequiredMixin, DetailView):
    model = Equipment
    template_name = "equipment/detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        eq = self.object
        ctx["status_events"] = eq.status_events.select_related("actor")
        ctx["work_orders"] = eq.work_orders.prefetch_related("remarks", "participants")
        ctx["open_complaints"] = eq.complaints.exclude(status="closed")
        ctx["can_engineer"] = self.request.user.is_engineer_or_admin
        ctx["completed_repair_count"] = eq.work_orders.filter(
            status="completed"
        ).count()
        schedule = getattr(eq, "ppm_schedule", None)
        ctx["ppm_schedule"] = schedule
        ctx["ppm_records"] = (
            schedule.records.select_related("work_order").prefetch_related(
                "engineers"
            )
            if schedule
            else []
        )
        if self.request.user.is_engineer_or_admin:
            from apps.ai import services as ai_services
            from apps.ai.models import ServiceManual

            ctx["risk_assessment"] = ai_services.latest_assessment(eq)
            ctx["service_manual"] = ServiceManual.for_equipment(eq)
        return ctx


class EquipmentCreateView(RoleRequiredMixin, View):
    allowed_roles = ENGINEER_ROLES

    def get(self, request):
        return render(request, "equipment/form.html", {"form": EquipmentForm()})

    def post(self, request):
        form = EquipmentForm(request.POST)
        if not form.is_valid():
            return render(request, "equipment/form.html", {"form": form})
        equipment = services.create_equipment(request.user, **form.cleaned_data)
        messages.success(request, f"Equipment {equipment.serial_number} registered.")
        return redirect("equipment_detail", pk=equipment.pk)


class EquipmentEditView(RoleRequiredMixin, View):
    allowed_roles = ENGINEER_ROLES

    def get(self, request, pk):
        equipment = get_object_or_404(Equipment, pk=pk)
        form = EquipmentForm(instance=equipment)
        return render(
            request, "equipment/form.html", {"form": form, "equipment": equipment}
        )

    def post(self, request, pk):
        equipment = get_object_or_404(Equipment, pk=pk)
        form = EquipmentForm(request.POST, instance=equipment)
        if not form.is_valid():
            return render(
                request, "equipment/form.html", {"form": form, "equipment": equipment}
            )
        fresh = Equipment.objects.get(pk=pk)
        services.update_equipment(fresh, request.user, **form.cleaned_data)
        messages.success(request, "Equipment updated.")
        return redirect("equipment_detail", pk=pk)


class EquipmentCondemnView(RoleRequiredMixin, View):
    allowed_roles = ENGINEER_ROLES

    def get(self, request, pk):
        equipment = get_object_or_404(Equipment, pk=pk)
        return render(
            request,
            "equipment/condemn.html",
            {"equipment": equipment, "form": CondemnForm()},
        )

    def post(self, request, pk):
        equipment = get_object_or_404(Equipment, pk=pk)
        form = CondemnForm(request.POST)
        if not form.is_valid():
            return render(
                request,
                "equipment/condemn.html",
                {"equipment": equipment, "form": form},
            )
        try:
            services.condemn_equipment(equipment, request.user, **form.cleaned_data)
        except DomainError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Equipment condemned. Its history is preserved.")
        return redirect("equipment_detail", pk=pk)


class EquipmentImportView(RoleRequiredMixin, View):
    allowed_roles = ENGINEER_ROLES
    template_name = "equipment/import.html"

    def get(self, request):
        return render(request, self.template_name)

    def post(self, request):
        upload = request.FILES.get("file")
        create_missing = bool(request.POST.get("create_missing_departments"))
        if not upload:
            messages.error(request, "Choose a .csv or .xlsx file first.")
            return render(request, self.template_name)
        try:
            rows = importer.parse_upload(upload, upload.name)
        except importer.ImportFormatError as exc:
            messages.error(request, str(exc))
            return render(request, self.template_name)
        request.session[SESSION_KEY] = {
            "rows": rows,
            "create_missing_departments": create_missing,
        }
        results = importer.validate_rows(
            rows, create_missing_departments=create_missing
        )
        return render(
            request,
            "equipment/import_preview.html",
            {
                "results": results,
                "ok_count": sum(1 for r in results if r.ok),
                "error_count": sum(1 for r in results if not r.ok),
                "create_missing_departments": create_missing,
            },
        )


class EquipmentImportConfirmView(RoleRequiredMixin, View):
    allowed_roles = ENGINEER_ROLES

    def post(self, request):
        stash = request.session.pop(SESSION_KEY, None)
        if not stash:
            messages.error(request, "Nothing to import — upload a file first.")
            return redirect("equipment_import")
        create_missing = stash["create_missing_departments"]
        results = importer.validate_rows(
            stash["rows"], create_missing_departments=create_missing
        )
        summary = importer.import_rows(
            request.user, results, create_missing_departments=create_missing
        )
        messages.success(
            request,
            f"{summary.created} imported, {len(summary.skipped)} skipped.",
        )
        if summary.skipped:
            details = "; ".join(
                f"line {r.line}: {', '.join(r.errors)}" for r in summary.skipped
            )
            messages.warning(request, f"Skipped — {details}")
        return redirect("equipment_list")
