from django.db import migrations

CATEGORIES = [
    (
        10,
        "electrical",
        "Electrical",
        "Mains supply, power supply unit, wiring, fuses or switches failed",
    ),
    (
        20,
        "electronic_boards",
        "Electronic boards",
        "A circuit board or module was repaired or replaced",
    ),
    (
        30,
        "display_monitor",
        "Display / Monitor",
        "Screen, touch panel or display output failed",
    ),
    (
        40,
        "mechanical",
        "Mechanical",
        "A moving or structural part was damaged, repaired or replaced",
    ),
    (50, "calibration", "Calibration", "Calibration or adjustment was needed"),
    (
        60,
        "software",
        "Software",
        "Firmware or software error, crash, freeze or update required",
    ),
    (
        70,
        "accessory_probe",
        "Accessory / Probe / Battery",
        "A probe, sensor, cable, battery or charging circuit failed, not the main unit",
    ),
    (80, "other", "Other", "Anything not covered above — explain in the remark"),
]

# Old text value -> new slug. battery_power folds into the accessory
# category, which now names battery in its title.
MAPPING = {
    "electrical": "electrical",
    "battery_power": "accessory_probe",
    "display_monitor": "display_monitor",
    "mechanical": "mechanical",
    "calibration": "calibration",
    "software": "software",
    "accessory_probe": "accessory_probe",
    "other": "other",
}


def forwards(apps, schema_editor):
    FaultCategory = apps.get_model("maintenance", "FaultCategory")
    WorkOrder = apps.get_model("maintenance", "WorkOrder")

    for sort_order, slug, name, description in CATEGORIES:
        FaultCategory.objects.update_or_create(
            slug=slug,
            defaults={
                "name": name,
                "description": description,
                "sort_order": sort_order,
            },
        )

    by_slug = {c.slug: c for c in FaultCategory.objects.all()}
    fallback = by_slug["other"]
    for wo in WorkOrder.objects.exclude(fault_category__isnull=True).exclude(
        fault_category=""
    ):
        wo.fault_category_new = by_slug.get(MAPPING.get(wo.fault_category), fallback)
        wo.save(update_fields=["fault_category_new"])


def backwards(apps, schema_editor):
    FaultCategory = apps.get_model("maintenance", "FaultCategory")
    WorkOrder = apps.get_model("maintenance", "WorkOrder")

    for wo in WorkOrder.objects.exclude(fault_category_new__isnull=True):
        wo.fault_category = wo.fault_category_new.slug
        # Clear the protected FK first — FaultCategory rows below cannot be
        # deleted while a work order still points at them.
        wo.fault_category_new = None
        wo.save(update_fields=["fault_category", "fault_category_new"])

    FaultCategory.objects.filter(
        slug__in=[slug for _, slug, _, _ in CATEGORIES]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("maintenance", "0004_faultcategory")]
    operations = [migrations.RunPython(forwards, backwards)]
