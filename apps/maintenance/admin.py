from django.contrib import admin

from .models import Complaint, FaultCategory, PPMRecord, PPMSchedule, Remark, WorkOrder


@admin.register(Complaint)
class ComplaintAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "equipment",
        "reporter",
        "status",
        "close_reason",
        "created_at",
    )
    list_filter = ("status", "close_reason")
    readonly_fields = [f.name for f in Complaint._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(WorkOrder)
class WorkOrderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "equipment",
        "status",
        "outcome",
        "fault_category",
        "opened_at",
    )
    list_filter = ("status", "fault_category")
    readonly_fields = [f.name for f in WorkOrder._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Remark)
class RemarkAdmin(admin.ModelAdmin):
    list_display = ("created_at", "work_order", "author", "kind")
    readonly_fields = [f.name for f in Remark._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PPMSchedule)
class PPMScheduleAdmin(admin.ModelAdmin):
    list_display = ("id", "equipment", "interval", "next_due", "active")
    list_filter = ("interval", "active")
    readonly_fields = [f.name for f in PPMSchedule._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(FaultCategory)
class FaultCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "description", "sort_order")
    ordering = ("sort_order", "name")

    def get_readonly_fields(self, request, obj=None):
        # The slug is a stable internal code: editable when creating a
        # category, frozen afterwards.
        return ("slug",) if obj else ()


@admin.register(PPMRecord)
class PPMRecordAdmin(admin.ModelAdmin):
    list_display = ("id", "schedule", "performed_at", "outcome", "recorded_by")
    list_filter = ("outcome",)
    readonly_fields = [f.name for f in PPMRecord._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
