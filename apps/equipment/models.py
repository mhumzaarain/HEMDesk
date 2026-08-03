from django.conf import settings
from django.db import models

from apps.core.models import AppendOnlyModel, NoDeleteModel


class EquipmentStatus(models.TextChoices):
    WORKING = "working", "Working"
    IN_REPAIR = "in_repair", "In Repair"
    CONDEMNED = "condemned", "Condemned"


class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)
    location = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Equipment(NoDeleteModel):
    name = models.CharField(max_length=200)
    manufacturer = models.CharField(max_length=200, blank=True)
    vendor = models.CharField(max_length=200, blank=True)
    model_number = models.CharField(max_length=100, blank=True)
    serial_number = models.CharField(max_length=100, unique=True)
    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name="equipment"
    )
    is_critical_asset = models.BooleanField(
        default=False,
        help_text="Downtime is tracked only for critical assets (MRI, CT, ...)",
    )
    purchase_date = models.DateField(null=True, blank=True)
    installation_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=EquipmentStatus.choices, default=EquipmentStatus.WORKING
    )
    condemned_at = models.DateTimeField(null=True, blank=True)
    condemned_location = models.CharField(max_length=200, blank=True)
    extra = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["name", "serial_number"]
        verbose_name_plural = "equipment"

    def __str__(self):
        return f"{self.name} {self.model_number} ({self.serial_number})"


class StatusEvent(AppendOnlyModel):
    equipment = models.ForeignKey(
        Equipment, on_delete=models.PROTECT, related_name="status_events"
    )
    old_status = models.CharField(max_length=20, choices=EquipmentStatus.choices)
    new_status = models.CharField(max_length=20, choices=EquipmentStatus.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="status_events"
    )
    remark = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    work_order = models.ForeignKey(
        "maintenance.WorkOrder",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="status_events",
    )

    class Meta:
        ordering = ["-created_at"]


class AccessoryStatus(models.TextChoices):
    WORKING = "working", "Working"
    FAULTY = "faulty", "Faulty"
    CONDEMNED = "condemned", "Condemned"


class AccessoryType(NoDeleteModel):
    """Catalog entry: 'ECG cable for Patient Monitor SVM 7523'. Backup spares
    in the in-house store are a counter here, not individual records."""

    name = models.CharField(max_length=200)
    equipment_name = models.CharField(
        max_length=200, help_text="The device this accessory is for."
    )
    stock_qty = models.PositiveIntegerField(
        default=0, help_text="New backup units in the in-house store."
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "equipment_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["name", "equipment_name"],
                name="unique_accessory_type_per_equipment",
            )
        ]

    def __str__(self):
        return f"{self.name} — {self.equipment_name}"


class Accessory(NoDeleteModel):
    """One physical accessory fitted on an equipment. Condemned units are
    kept forever (no-delete convention)."""

    type = models.ForeignKey(
        AccessoryType, on_delete=models.PROTECT, related_name="units"
    )
    equipment = models.ForeignKey(
        Equipment, on_delete=models.PROTECT, related_name="accessories"
    )
    status = models.CharField(
        max_length=20, choices=AccessoryStatus.choices, default=AccessoryStatus.WORKING
    )
    serial_number = models.CharField(
        max_length=100, blank=True, help_text="Many accessories are not serialized."
    )
    condemned_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["type__name", "id"]
        verbose_name_plural = "accessories"

    def __str__(self):
        return f"{self.type.name} on {self.equipment.serial_number}"
