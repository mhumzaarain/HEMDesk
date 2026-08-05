from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import View

from apps.accounts.mixins import RoleRequiredMixin
from apps.accounts.models import Roles
from apps.equipment.models import Equipment
from apps.maintenance.models import WorkOrder

from .models import AssistantMessage, AssistantRole, ManualStatus, ServiceManual

ENGINEER_ROLES = (Roles.ENGINEER, Roles.ADMIN)


class ManualListView(RoleRequiredMixin, View):
    allowed_roles = ENGINEER_ROLES

    def get(self, request):
        return render(
            request,
            "ai/manuals.html",
            {"manuals": ServiceManual.objects.order_by("manufacturer", "model_number")},
        )

    def post(self, request):
        from . import tasks

        manufacturer = request.POST.get("manufacturer", "").strip()
        model_number = request.POST.get("model_number", "").strip()
        title = request.POST.get("title", "").strip()
        upload = request.FILES.get("file")
        if not all([manufacturer, model_number, title, upload]):
            messages.error(request, "All fields including the PDF are required.")
            return redirect("manual_list")
        existing = ServiceManual.objects.filter(
            manufacturer__iexact=manufacturer, model_number__iexact=model_number
        ).first()
        if existing and existing.file:
            existing.file.delete(save=False)
        manual, _ = ServiceManual.objects.update_or_create(
            manufacturer__iexact=manufacturer,
            model_number__iexact=model_number,
            defaults={
                "manufacturer": manufacturer,
                "model_number": model_number,
                "title": title,
                "file": upload,
                "uploaded_by": request.user,
                "status": ManualStatus.PROCESSING,
                "status_note": "",
            },
        )
        tasks.process_manual.defer(manual_id=manual.id)
        messages.success(request, f"{title} uploaded — processing in background.")
        return redirect("manual_list")


def _assistant_context(request, equipment_id):
    equipment = get_object_or_404(Equipment, pk=equipment_id)
    work_order = None
    wo_id = request.GET.get("wo")
    if wo_id:
        work_order = get_object_or_404(WorkOrder, pk=wo_id, equipment=equipment)
    return {
        "equipment": equipment,
        "work_order": work_order,
        "chat_messages": equipment.assistant_messages.select_related("user"),
    }


class AssistantMessagesView(RoleRequiredMixin, View):
    allowed_roles = ENGINEER_ROLES

    def get(self, request, equipment_id):
        return render(
            request,
            "ai/_assistant_messages.html",
            _assistant_context(request, equipment_id),
        )


class AssistantSendView(RoleRequiredMixin, View):
    allowed_roles = ENGINEER_ROLES

    def post(self, request, equipment_id):
        from . import tasks

        context = _assistant_context(request, equipment_id)
        content = request.POST.get("content", "").strip()

        from apps.maintenance.models import FaultCategory

        fault_category = request.POST.get("fault_category", "").strip()
        if fault_category not in FaultCategory.values:
            fault_category = ""

        if content:
            message = AssistantMessage.objects.create(
                equipment=context["equipment"],
                work_order=context["work_order"],
                user=request.user,
                role=AssistantRole.USER,
                content=content,
            )
            tasks.answer_assistant_chat.defer(
                message_id=message.id, fault_category=fault_category or None
            )
        return render(request, "ai/_assistant_messages.html", context)
