import pytest

from apps.maintenance.models import FaultCategory
from apps.maintenance.services import (
    complete_work_order,
    open_work_order,
    start_repair,
)

pytestmark = pytest.mark.django_db

EXPECTED_SLUGS = [
    "electrical",
    "electronic_boards",
    "display_monitor",
    "mechanical",
    "calibration",
    "software",
    "accessory_probe",
    "other",
]


def test_eight_categories_are_seeded_in_display_order():
    assert list(FaultCategory.objects.values_list("slug", flat=True)) == EXPECTED_SLUGS


def test_every_seeded_category_has_a_description():
    for category in FaultCategory.objects.all():
        assert category.description, f"{category.slug} has no description"


def test_battery_is_named_in_the_accessory_category():
    accessory = FaultCategory.objects.get(slug="accessory_probe")
    assert accessory.name == "Accessory / Probe / Battery"
    assert "battery" in accessory.description.lower()


def test_str_is_the_name():
    assert str(FaultCategory.objects.get(slug="mechanical")) == "Mechanical"


def test_slug_is_unique():
    from django.db import IntegrityError

    with pytest.raises(IntegrityError):
        FaultCategory.objects.create(name="Duplicate", slug="mechanical")


def test_category_in_use_cannot_be_deleted(equipment, engineer, fault):
    from django.db.models import ProtectedError

    wo = start_repair(open_work_order(equipment, engineer), engineer)
    complete_work_order(wo, engineer, fault_category=fault("mechanical"))

    with pytest.raises(ProtectedError):
        fault("mechanical").delete()


def test_unused_category_can_be_deleted():
    FaultCategory.objects.create(name="Typo", slug="typo").delete()
    assert not FaultCategory.objects.filter(slug="typo").exists()


def test_renaming_a_category_shows_on_existing_work_orders(equipment, engineer, fault):
    wo = start_repair(open_work_order(equipment, engineer), engineer)
    complete_work_order(wo, engineer, fault_category=fault("mechanical"))

    category = fault("mechanical")
    category.name = "Mechanical / Structural"
    category.save()

    wo.refresh_from_db()
    assert str(wo.fault_category) == "Mechanical / Structural"


def test_completing_without_a_category_is_rejected(equipment, engineer):
    wo = start_repair(open_work_order(equipment, engineer), engineer)
    with pytest.raises(ValueError):
        complete_work_order(wo, engineer, fault_category=None)


def test_admin_can_add_a_category_with_the_documented_fields(client, django_user_model):
    """docs/admin/reference-data.md tells administrators to fill in Name,
    Description and Sort order only — the internal code is derived."""
    boss = django_user_model.objects.create_superuser(
        username="root-fc", password="pw", employee_id="EMP-FC1"
    )
    client.force_login(boss)

    response = client.post(
        "/admin/maintenance/faultcategory/add/",
        {
            "name": "Water Ingress",
            "description": "Fluid spilled into the enclosure.",
            "sort_order": "150",
        },
    )

    assert response.status_code == 302, response.content.decode()
    category = FaultCategory.objects.get(name="Water Ingress")
    assert category.slug == "water-ingress"


def test_the_audit_entry_records_the_slug_not_the_name(equipment, engineer, fault):
    from apps.core.models import AuditLog

    wo = start_repair(open_work_order(equipment, engineer), engineer)
    complete_work_order(wo, engineer, fault_category=fault("electrical"))

    entry = AuditLog.objects.filter(verb="workorder.completed").latest("created_at")
    assert entry.changes["fault_category"] == "electrical"
