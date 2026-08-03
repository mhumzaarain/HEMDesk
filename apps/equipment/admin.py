from django.contrib import admin

from .models import (
    Accessory,
    AccessoryEvent,
    AccessoryType,
    Department,
    Equipment,
    StatusEvent,
)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "location")


@admin.register(Equipment)
class EquipmentAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "model_number",
        "serial_number",
        "department",
        "status",
        "is_critical_asset",
    )
    list_filter = ("status", "department", "is_critical_asset")
    search_fields = ("name", "serial_number", "model_number", "manufacturer")
    readonly_fields = ("status", "condemned_at", "condemned_location")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StatusEvent)
class StatusEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "equipment", "old_status", "new_status", "actor")
    readonly_fields = [f.name for f in StatusEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AccessoryType)
class AccessoryTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "equipment_name", "stock_qty")
    search_fields = ("name", "equipment_name")
    readonly_fields = ("stock_qty",)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Accessory)
class AccessoryAdmin(admin.ModelAdmin):
    list_display = ("type", "equipment", "status", "serial_number")
    list_filter = ("status",)
    search_fields = (
        "type__name",
        "serial_number",
        "equipment__serial_number",
        "equipment__name",
    )
    readonly_fields = ("status", "condemned_at")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AccessoryEvent)
class AccessoryEventAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "kind",
        "accessory_type",
        "equipment",
        "work_order",
        "actor",
    )
    readonly_fields = [f.name for f in AccessoryEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
