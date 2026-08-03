from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.generic import DetailView, ListView, View

from apps.accounts.mixins import RoleRequiredMixin
from apps.accounts.models import Roles
from apps.core.exceptions import DomainError
from apps.maintenance.models import WorkOrder

from . import importer, services
from .forms import (
    AccessoryAttachForm,
    AccessoryCondemnForm,
    AccessoryEditForm,
    AccessoryRepairForm,
    AccessoryReplaceForm,
    AccessoryTypeForm,
    CondemnForm,
    EquipmentForm,
    StockAdjustForm,
)
from .models import (
    Accessory,
    AccessoryEventKind,
    AccessoryStatus,
    AccessoryType,
    Equipment,
    EquipmentStatus,
)

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
        ctx["accessories"] = eq.accessories.select_related("type")
        replaced_breakdown = list(
            eq.accessory_events.filter(kind=AccessoryEventKind.REPLACED)
            .values("accessory_type__name")
            .annotate(n=Count("id"))
            .order_by("-n")
        )
        ctx["accessory_replaced_total"] = sum(r["n"] for r in replaced_breakdown)
        ctx["accessory_replaced_breakdown"] = replaced_breakdown
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


class AccessoryTypeListView(RoleRequiredMixin, ListView):
    allowed_roles = ENGINEER_ROLES
    template_name = "equipment/accessory_type_list.html"

    def get_queryset(self):
        return AccessoryType.objects.annotate(
            fitted_count=Count(
                "units", filter=~Q(units__status=AccessoryStatus.CONDEMNED)
            )
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["restock"] = AccessoryType.objects.filter(stock_qty=0)
        return ctx


class AccessoryTypeCreateView(RoleRequiredMixin, View):
    allowed_roles = ENGINEER_ROLES

    def get(self, request):
        return render(
            request,
            "equipment/accessory_form.html",
            {
                "form": AccessoryTypeForm(),
                "form_title": "Add accessory type",
                "form_subtitle": "Define a catalog entry once; reuse it everywhere.",
                "cancel_url": reverse("accessory_type_list"),
            },
        )

    def post(self, request):
        form = AccessoryTypeForm(request.POST)
        if not form.is_valid():
            return render(
                request,
                "equipment/accessory_form.html",
                {
                    "form": form,
                    "form_title": "Add accessory type",
                    "form_subtitle": (
                        "Define a catalog entry once; reuse it everywhere."
                    ),
                    "cancel_url": reverse("accessory_type_list"),
                },
            )
        services.create_accessory_type(request.user, **form.cleaned_data)
        messages.success(request, "Accessory type added.")
        return redirect("accessory_type_list")


class AccessoryTypeEditView(RoleRequiredMixin, View):
    allowed_roles = ENGINEER_ROLES

    def _render(self, request, form, accessory_type):
        return render(
            request,
            "equipment/accessory_form.html",
            {
                "form": form,
                "form_title": f"Edit {accessory_type.name}",
                "form_subtitle": accessory_type.equipment_name,
                "cancel_url": reverse("accessory_type_list"),
            },
        )

    def get(self, request, pk):
        accessory_type = get_object_or_404(AccessoryType, pk=pk)
        return self._render(
            request, AccessoryTypeForm(instance=accessory_type), accessory_type
        )

    def post(self, request, pk):
        accessory_type = get_object_or_404(AccessoryType, pk=pk)
        form = AccessoryTypeForm(request.POST, instance=accessory_type)
        if not form.is_valid():
            return self._render(request, form, accessory_type)
        fresh = AccessoryType.objects.get(pk=pk)
        services.update_accessory_type(fresh, request.user, **form.cleaned_data)
        messages.success(request, "Accessory type updated.")
        return redirect("accessory_type_list")


class AccessoryStockAdjustView(RoleRequiredMixin, View):
    allowed_roles = ENGINEER_ROLES

    def _render(self, request, form, accessory_type):
        return render(
            request,
            "equipment/accessory_form.html",
            {
                "form": form,
                "form_title": f"Adjust stock — {accessory_type.name}",
                "form_subtitle": (
                    f"{accessory_type.equipment_name} · currently in store: "
                    f"{accessory_type.stock_qty}"
                ),
                "cancel_url": reverse("accessory_type_list"),
            },
        )

    def get(self, request, pk):
        accessory_type = get_object_or_404(AccessoryType, pk=pk)
        return self._render(request, StockAdjustForm(), accessory_type)

    def post(self, request, pk):
        accessory_type = get_object_or_404(AccessoryType, pk=pk)
        form = StockAdjustForm(request.POST)
        if not form.is_valid():
            return self._render(request, form, accessory_type)
        delta = form.cleaned_data["quantity"]
        if form.cleaned_data["action"] == "remove":
            delta = -delta
        try:
            services.adjust_stock(
                accessory_type, request.user, delta, form.cleaned_data["reason"]
            )
        except DomainError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Stock updated.")
        return redirect("accessory_type_list")


class AccessoryAttachView(RoleRequiredMixin, View):
    allowed_roles = ENGINEER_ROLES

    def _render(self, request, form, equipment):
        return render(
            request,
            "equipment/accessory_form.html",
            {
                "form": form,
                "form_title": "Attach accessory",
                "form_subtitle": (
                    f"{equipment.name} {equipment.model_number} · "
                    f"{equipment.serial_number}"
                ),
                "cancel_url": reverse("equipment_detail", args=[equipment.pk]),
            },
        )

    def get(self, request, pk):
        equipment = get_object_or_404(Equipment, pk=pk)
        return self._render(request, AccessoryAttachForm(), equipment)

    def post(self, request, pk):
        equipment = get_object_or_404(Equipment, pk=pk)
        form = AccessoryAttachForm(request.POST)
        if not form.is_valid():
            return self._render(request, form, equipment)
        try:
            services.attach_accessory(
                equipment,
                request.user,
                form.cleaned_data["accessory_type"],
                from_stock=form.cleaned_data["from_stock"],
                serial_number=form.cleaned_data["serial_number"],
                notes=form.cleaned_data["notes"],
            )
        except DomainError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Accessory attached.")
        return redirect("equipment_detail", pk=pk)


class AccessoryEditView(RoleRequiredMixin, View):
    allowed_roles = ENGINEER_ROLES

    def _render(self, request, form, accessory):
        return render(
            request,
            "equipment/accessory_form.html",
            {
                "form": form,
                "form_title": f"Edit {accessory.type.name}",
                "form_subtitle": (
                    f"On {accessory.equipment.name} "
                    f"{accessory.equipment.serial_number}"
                ),
                "cancel_url": reverse(
                    "equipment_detail", args=[accessory.equipment_id]
                ),
            },
        )

    def get(self, request, pk):
        accessory = get_object_or_404(
            Accessory.objects.select_related("type", "equipment"), pk=pk
        )
        return self._render(request, AccessoryEditForm(instance=accessory), accessory)

    def post(self, request, pk):
        accessory = get_object_or_404(
            Accessory.objects.select_related("type", "equipment"), pk=pk
        )
        form = AccessoryEditForm(request.POST, instance=accessory)
        if not form.is_valid():
            return self._render(request, form, accessory)
        fresh = Accessory.objects.get(pk=pk)
        try:
            services.update_accessory(fresh, request.user, **form.cleaned_data)
        except DomainError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Accessory updated.")
        return redirect("equipment_detail", pk=accessory.equipment_id)


class AccessoryCondemnView(RoleRequiredMixin, View):
    allowed_roles = ENGINEER_ROLES

    def get(self, request, pk):
        accessory = get_object_or_404(
            Accessory.objects.select_related("type", "equipment"), pk=pk
        )
        return render(
            request,
            "equipment/accessory_condemn.html",
            {"accessory": accessory, "form": AccessoryCondemnForm()},
        )

    def post(self, request, pk):
        accessory = get_object_or_404(
            Accessory.objects.select_related("type", "equipment"), pk=pk
        )
        form = AccessoryCondemnForm(request.POST)
        if not form.is_valid():
            return render(
                request,
                "equipment/accessory_condemn.html",
                {"accessory": accessory, "form": form},
            )
        try:
            services.condemn_accessory(
                accessory, request.user, form.cleaned_data["reason"]
            )
        except DomainError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Accessory condemned. Its record is preserved.")
        return redirect("equipment_detail", pk=accessory.equipment_id)


class AccessoryMarkFaultyView(RoleRequiredMixin, View):
    allowed_roles = ENGINEER_ROLES

    def post(self, request, pk, wo_pk):
        accessory = get_object_or_404(Accessory, pk=pk)
        get_object_or_404(WorkOrder, pk=wo_pk)
        try:
            services.update_accessory(
                accessory, request.user, status=AccessoryStatus.FAULTY
            )
        except DomainError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Accessory marked faulty.")
        return redirect("workorder_detail", pk=wo_pk)


class AccessoryRepairView(RoleRequiredMixin, View):
    allowed_roles = ENGINEER_ROLES

    def _render(self, request, form, accessory, work_order):
        return render(
            request,
            "equipment/accessory_form.html",
            {
                "form": form,
                "form_title": f"Repair {accessory.type.name}",
                "form_subtitle": f"WO #{work_order.pk} · {accessory.equipment}",
                "cancel_url": reverse("workorder_detail", args=[work_order.pk]),
            },
        )

    def get(self, request, pk, wo_pk):
        accessory = get_object_or_404(
            Accessory.objects.select_related("type", "equipment"), pk=pk
        )
        work_order = get_object_or_404(WorkOrder, pk=wo_pk)
        return self._render(request, AccessoryRepairForm(), accessory, work_order)

    def post(self, request, pk, wo_pk):
        accessory = get_object_or_404(
            Accessory.objects.select_related("type", "equipment"), pk=pk
        )
        work_order = get_object_or_404(WorkOrder, pk=wo_pk)
        form = AccessoryRepairForm(request.POST)
        if not form.is_valid():
            return self._render(request, form, accessory, work_order)
        try:
            services.repair_accessory(
                accessory, request.user, work_order, form.cleaned_data["remark"]
            )
        except DomainError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Accessory repaired.")
        return redirect("workorder_detail", pk=wo_pk)


class AccessoryReplaceView(RoleRequiredMixin, View):
    allowed_roles = ENGINEER_ROLES

    def _render(self, request, form, accessory, work_order):
        return render(
            request,
            "equipment/accessory_form.html",
            {
                "form": form,
                "form_title": f"Replace {accessory.type.name}",
                "form_subtitle": (
                    f"WO #{work_order.pk} · in store: "
                    f"{accessory.type.stock_qty}"
                ),
                "cancel_url": reverse("workorder_detail", args=[work_order.pk]),
            },
        )

    def get(self, request, pk, wo_pk):
        accessory = get_object_or_404(
            Accessory.objects.select_related("type", "equipment"), pk=pk
        )
        work_order = get_object_or_404(WorkOrder, pk=wo_pk)
        return self._render(request, AccessoryReplaceForm(), accessory, work_order)

    def post(self, request, pk, wo_pk):
        accessory = get_object_or_404(
            Accessory.objects.select_related("type", "equipment"), pk=pk
        )
        work_order = get_object_or_404(WorkOrder, pk=wo_pk)
        form = AccessoryReplaceForm(request.POST)
        if not form.is_valid():
            return self._render(request, form, accessory, work_order)
        try:
            services.replace_accessory(
                accessory,
                request.user,
                work_order,
                remark=form.cleaned_data["remark"],
                serial_number=form.cleaned_data["serial_number"],
            )
        except DomainError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Accessory replaced from backup stock.")
        return redirect("workorder_detail", pk=wo_pk)
