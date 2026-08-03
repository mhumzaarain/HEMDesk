import calendar
from datetime import date, timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import AppendOnlyModel, NoDeleteModel
from apps.equipment.models import Equipment


class ComplaintStatus(models.TextChoices):
    OPEN = "open", "Open"
    ATTACHED = "attached", "Attached to Work Order"
    CLOSED = "closed", "Closed"


class CloseReason(models.TextChoices):
    RESOLVED = "resolved", "Resolved"
    DUPLICATE = "duplicate", "Duplicate"
    NO_FAULT = "no_fault", "No Fault Found"


class WorkOrderStatus(models.TextChoices):
    OPEN = "open", "Open"
    IN_PROGRESS = "in_progress", "In Progress"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


class WorkOrderOutcome(models.TextChoices):
    REPAIRED = "repaired", "Repaired"
    CONDEMNED = "condemned", "Condemned"


class FaultCategory(models.TextChoices):
    ELECTRICAL = "electrical", "Electrical"
    BATTERY_POWER = "battery_power", "Battery / Power"
    DISPLAY_MONITOR = "display_monitor", "Display / Monitor"
    MECHANICAL = "mechanical", "Mechanical"
    CALIBRATION = "calibration", "Calibration"
    SOFTWARE = "software", "Software"
    ACCESSORY_PROBE = "accessory_probe", "Accessory / Probe"
    OTHER = "other", "Other"


class RemarkKind(models.TextChoices):
    NOTE = "note", "Note"
    DELAY = "delay", "Delay"
    SYSTEM = "system", "System"


class FunctionalConfirmation(models.TextChoices):
    FUNCTIONAL = "functional", "Functional"
    NOT_FUNCTIONAL = "not_functional", "Not functional"


ACTIVE_WORKORDER_STATUSES = (WorkOrderStatus.OPEN, WorkOrderStatus.IN_PROGRESS)


class WorkOrder(NoDeleteModel):
    equipment = models.ForeignKey(
        Equipment, on_delete=models.PROTECT, related_name="work_orders"
    )
    status = models.CharField(
        max_length=20, choices=WorkOrderStatus.choices, default=WorkOrderStatus.OPEN
    )
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="workorders_opened",
    )
    opened_at = models.DateTimeField(auto_now_add=True)
    repair_started_at = models.DateTimeField(null=True, blank=True)
    repair_completed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="workorders_closed",
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField(
        max_length=20, choices=WorkOrderOutcome.choices, null=True, blank=True
    )
    fault_category = models.CharField(
        max_length=30,
        choices=FaultCategory.choices,
        null=True,
        blank=True,
        help_text="Required when completing a repair.",
    )
    participants = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="workorders_participated",
        help_text="Engineers who worked on this repair.",
    )

    class Meta:
        ordering = ["-opened_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["equipment"],
                condition=~models.Q(
                    status__in=[WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED]
                ),
                name="one_active_workorder_per_equipment",
            )
        ]

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_WORKORDER_STATUSES

    def __str__(self):
        return f"WO #{self.pk} — {self.equipment}"


class Complaint(NoDeleteModel):
    equipment = models.ForeignKey(
        Equipment, on_delete=models.PROTECT, related_name="complaints"
    )
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="complaints_reported",
    )
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=20, choices=ComplaintStatus.choices, default=ComplaintStatus.OPEN
    )
    work_order = models.ForeignKey(
        WorkOrder,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="complaints",
    )
    close_reason = models.CharField(
        max_length=20, choices=CloseReason.choices, null=True, blank=True
    )
    duplicate_of = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="duplicates",
    )
    close_note = models.TextField(blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="complaints_closed",
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    functional_confirmation = models.CharField(
        max_length=20, choices=FunctionalConfirmation.choices, null=True, blank=True
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)

    @property
    def is_awaiting_confirmation(self) -> bool:
        return (
            self.status == ComplaintStatus.CLOSED
            and self.close_reason == CloseReason.RESOLVED
            and self.functional_confirmation is None
            and self.work_order_id is not None
            and self.work_order.outcome == WorkOrderOutcome.REPAIRED
        )

    @property
    def age_hours(self) -> float:
        from django.utils import timezone

        return (timezone.now() - self.created_at).total_seconds() / 3600.0

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Complaint #{self.pk} — {self.equipment}"


class Remark(AppendOnlyModel):
    work_order = models.ForeignKey(
        WorkOrder, on_delete=models.PROTECT, related_name="remarks"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="remarks"
    )
    text = models.TextField()
    kind = models.CharField(
        max_length=10, choices=RemarkKind.choices, default=RemarkKind.NOTE
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class PPMInterval(models.TextChoices):
    MONTHLY = "monthly", "Monthly"
    QUARTERLY = "quarterly", "Quarterly"
    BIANNUAL = "biannual", "Every 6 months"
    ANNUAL = "annual", "Annual"


PPM_INTERVAL_MONTHS = {
    PPMInterval.MONTHLY: 1,
    PPMInterval.QUARTERLY: 3,
    PPMInterval.BIANNUAL: 6,
    PPMInterval.ANNUAL: 12,
}

PPM_DUE_SOON_DAYS = 30


class PPMOutcome(models.TextChoices):
    PASSED = "passed", "Passed"
    PASSED_WITH_REMARKS = "passed_with_remarks", "Passed with remarks"
    FAILED = "failed", "Failed"


def add_months(d: date, months: int) -> date:
    """d + months, clamping to the last day of the target month
    (Jan 31 + 1 month -> Feb 28/29)."""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


class PPMSchedule(NoDeleteModel):
    equipment = models.OneToOneField(
        Equipment, on_delete=models.PROTECT, related_name="ppm_schedule"
    )
    interval = models.CharField(max_length=20, choices=PPMInterval.choices)
    next_due = models.DateField()
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["next_due"]

    @property
    def interval_months(self) -> int:
        return PPM_INTERVAL_MONTHS[self.interval]

    @property
    def is_overdue(self) -> bool:
        return self.next_due < timezone.localdate()

    @property
    def is_due_soon(self) -> bool:
        today = timezone.localdate()
        return today <= self.next_due <= today + timedelta(days=PPM_DUE_SOON_DAYS)

    def __str__(self):
        return f"PPM {self.get_interval_display()} — {self.equipment}"


class PPMRecord(AppendOnlyModel):
    schedule = models.ForeignKey(
        PPMSchedule, on_delete=models.PROTECT, related_name="records"
    )
    due_date = models.DateField(
        help_text="Snapshot of the schedule's next_due when this PPM was recorded."
    )
    performed_at = models.DateField()
    outcome = models.CharField(max_length=30, choices=PPMOutcome.choices)
    remarks = models.TextField(blank=True)
    engineers = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="ppm_records"
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ppm_records_recorded",
    )
    work_order = models.ForeignKey(
        WorkOrder,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="ppm_records",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-performed_at", "-created_at"]

    def __str__(self):
        return f"PPM on {self.performed_at} — {self.schedule.equipment}"
