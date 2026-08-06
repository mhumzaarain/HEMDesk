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


@pytest.fixture
def admin_client_fc(client, django_user_model):
    boss = django_user_model.objects.create_superuser(
        username="root-slug", password="pw", employee_id="EMP-FC2"
    )
    client.force_login(boss)
    return client


def add_category(admin_client_fc, **fields):
    payload = {"name": "", "slug": "", "description": "", "sort_order": "100"}
    payload.update(fields)
    return admin_client_fc.post("/admin/maintenance/faultcategory/add/", payload)


def form_errors(response):
    """The add form's errors, keyed by field name ("__all__" for non-field)."""
    return response.context["adminform"].form.errors


def test_the_add_form_does_not_prefill_the_code_in_the_browser(admin_client_fc):
    """The code is derived on the server. If the admin site also filled the box
    in with JavaScript, a real browser would post a non-empty code and take a
    different validation path from the one every other test here exercises."""
    response = admin_client_fc.get("/admin/maintenance/faultcategory/add/")

    assert response.status_code == 200
    adminform = response.context["adminform"]
    assert adminform.prepopulated_fields == [], adminform.prepopulated_fields
    # The admin always emits the attribute; what matters is that it is empty,
    # so the JavaScript has no field to drive.
    assert 'data-prepopulated-fields="[]"' in response.content.decode()
    assert adminform.form["slug"].value() in (None, "")


def test_a_hand_typed_clashing_code_fails_gracefully(admin_client_fc):
    """With the prepopulating JavaScript gone, a non-empty code can only be
    typed by hand. It must still be a form error rather than a crash."""
    response = add_category(
        admin_client_fc, name="Electrical faults", slug="electrical"
    )

    assert response.status_code == 200, response.status_code
    errors = form_errors(response)
    assert list(errors) == ["slug"], dict(errors)
    assert not FaultCategory.objects.filter(name="Electrical faults").exists()


def test_saving_a_name_that_yields_no_code_is_refused_outright():
    """No form involved — the seeder, a management command, the shell. Letting
    a row with an empty code exist would break the assistant's filter and make
    the change form uneditable, so refuse it at the source."""
    with pytest.raises(ValueError, match="internal code"):
        FaultCategory.objects.create(name="水浸")

    assert not FaultCategory.objects.filter(name="水浸").exists()


def test_a_name_clashing_on_code_is_refused_not_crashed(admin_client_fc):
    FaultCategory.objects.create(name="Battery")

    response = add_category(admin_client_fc, name="battery")

    assert response.status_code == 200, response.status_code
    errors = form_errors(response)
    # The administrator typed a name, so the message belongs on Name — and it
    # must say which existing category is in the way.
    assert list(errors) == ["name"], dict(errors)
    assert "already uses the internal code" in errors["name"][0]
    assert "Battery" in errors["name"][0]
    assert "battery" in errors["name"][0]
    assert "already uses the internal code" in response.content.decode()
    assert FaultCategory.objects.filter(name="battery").count() == 0


def test_a_punctuation_variant_clashing_on_code_is_refused(admin_client_fc):
    FaultCategory.objects.create(name="Battery")

    response = add_category(admin_client_fc, name="Battery!")

    assert response.status_code == 200, response.status_code
    errors = form_errors(response)
    assert list(errors) == ["name"], dict(errors)
    assert "already uses the internal code" in errors["name"][0]
    assert FaultCategory.objects.filter(name="Battery!").count() == 0


def test_a_name_that_yields_no_code_asks_for_one(admin_client_fc):
    response = add_category(admin_client_fc, name="水浸")

    assert response.status_code == 200, response.status_code
    errors = form_errors(response)
    # The fix is to type a code, so the message belongs on the code box.
    assert list(errors) == ["slug"], dict(errors)
    assert "An internal code could not be built" in errors["slug"][0]
    assert "An internal code could not be built" in response.content.decode()
    assert not FaultCategory.objects.filter(name="水浸").exists()


def test_a_name_that_yields_no_code_is_accepted_with_a_typed_code(admin_client_fc):
    response = add_category(admin_client_fc, name="水浸", slug="water-ingress-cn")

    assert response.status_code == 302, response.content.decode()
    assert FaultCategory.objects.get(name="水浸").slug == "water-ingress-cn"


def test_renaming_a_category_leaves_its_code_untouched(fault):
    category = fault("mechanical")
    category.name = "Mechanical / Structural"
    category.full_clean()
    category.save()

    category.refresh_from_db()
    assert category.slug == "mechanical"


def test_a_long_name_does_not_leave_a_trailing_hyphen(admin_client_fc):
    long_name = "Electrical supply and distribution wire fault"

    response = add_category(admin_client_fc, name=long_name)

    assert response.status_code == 302, response.content.decode()
    slug = FaultCategory.objects.get(name=long_name).slug
    assert len(slug) <= 40
    assert not slug.endswith("-"), slug


def test_the_audit_entry_records_the_slug_not_the_name(equipment, engineer, fault):
    from apps.core.models import AuditLog

    wo = start_repair(open_work_order(equipment, engineer), engineer)
    complete_work_order(wo, engineer, fault_category=fault("electrical"))

    entry = AuditLog.objects.filter(verb="workorder.completed").latest("created_at")
    assert entry.changes["fault_category"] == "electrical"
