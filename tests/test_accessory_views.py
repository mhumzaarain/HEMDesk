import pytest
from django.urls import reverse

from apps.equipment.models import AccessoryStatus, AccessoryType

pytestmark = pytest.mark.django_db


def test_staff_cannot_see_catalog(client, staff_user):
    client.force_login(staff_user)
    assert client.get(reverse("accessory_type_list")).status_code == 403


def test_staff_cannot_open_catalog_write_pages(client, staff_user, accessory_type):
    client.force_login(staff_user)
    urls = [
        reverse("accessory_type_create"),
        reverse("accessory_type_edit", args=[accessory_type.pk]),
        reverse("accessory_stock_adjust", args=[accessory_type.pk]),
    ]
    for url in urls:
        assert client.get(url).status_code == 403


def test_engineer_sees_catalog_with_counts(
    client, engineer, accessory_type, fitted_accessory
):
    client.force_login(engineer)
    response = client.get(reverse("accessory_type_list"))
    assert response.status_code == 200
    assert b"ECG cable" in response.content
    assert b"In store: 0" in response.content
    assert b"Fitted: 1" in response.content


def test_engineer_creates_type(client, engineer):
    client.force_login(engineer)
    response = client.post(
        reverse("accessory_type_create"),
        {
            "name": "SpO2 probe",
            "equipment_name": "Patient Monitor SVM 7523",
            "notes": "",
        },
    )
    assert response.status_code == 302
    assert AccessoryType.objects.filter(name="SpO2 probe").exists()


def test_duplicate_type_shows_form_error(client, engineer, accessory_type):
    client.force_login(engineer)
    response = client.post(
        reverse("accessory_type_create"),
        {
            "name": "ECG cable",
            "equipment_name": "Patient Monitor SVM 7523",
            "notes": "",
        },
    )
    assert response.status_code == 200
    assert AccessoryType.objects.count() == 1


def test_engineer_edits_type(client, engineer, accessory_type):
    client.force_login(engineer)
    response = client.post(
        reverse("accessory_type_edit", args=[accessory_type.pk]),
        {
            "name": "ECG cable 5-lead",
            "equipment_name": "Patient Monitor SVM 7523",
            "notes": "",
        },
    )
    assert response.status_code == 302
    accessory_type.refresh_from_db()
    assert accessory_type.name == "ECG cable 5-lead"


def test_engineer_adjusts_stock_via_view(client, engineer, accessory_type):
    client.force_login(engineer)
    response = client.post(
        reverse("accessory_stock_adjust", args=[accessory_type.pk]),
        {"action": "add", "quantity": 5, "reason": "Received shipment"},
    )
    assert response.status_code == 302
    accessory_type.refresh_from_db()
    assert accessory_type.stock_qty == 5


def test_stock_remove_below_zero_shows_error(client, engineer, accessory_type):
    client.force_login(engineer)
    response = client.post(
        reverse("accessory_stock_adjust", args=[accessory_type.pk]),
        {"action": "remove", "quantity": 1, "reason": "oops"},
        follow=True,
    )
    accessory_type.refresh_from_db()
    assert accessory_type.stock_qty == 0
    assert b"Stock cannot go below zero." in response.content


def test_staff_sees_fitted_list_but_no_buttons(
    client, staff_user, equipment, fitted_accessory
):
    client.force_login(staff_user)
    response = client.get(reverse("equipment_detail", args=[equipment.pk]))
    assert response.status_code == 200
    assert b"ECG cable" in response.content
    assert b"Attach accessory" not in response.content


def test_staff_cannot_open_accessory_write_pages(
    client, staff_user, equipment, fitted_accessory
):
    client.force_login(staff_user)
    urls = [
        reverse("accessory_attach", args=[equipment.pk]),
        reverse("accessory_edit", args=[fitted_accessory.pk]),
        reverse("accessory_condemn", args=[fitted_accessory.pk]),
    ]
    for url in urls:
        assert client.get(url).status_code == 403


def test_engineer_attaches_via_view(client, engineer, equipment, accessory_type):
    from apps.equipment import services

    services.adjust_stock(accessory_type, engineer, 1, "Initial stock")
    client.force_login(engineer)
    response = client.post(
        reverse("accessory_attach", args=[equipment.pk]),
        {
            "accessory_type": accessory_type.pk,
            "serial_number": "ACC-77",
            "from_stock": "on",
            "notes": "",
        },
    )
    assert response.status_code == 302
    accessory_type.refresh_from_db()
    assert accessory_type.stock_qty == 0
    assert equipment.accessories.filter(serial_number="ACC-77").exists()


def test_attach_at_zero_stock_shows_error(
    client, engineer, equipment, accessory_type
):
    client.force_login(engineer)
    response = client.post(
        reverse("accessory_attach", args=[equipment.pk]),
        {
            "accessory_type": accessory_type.pk,
            "serial_number": "",
            "from_stock": "on",
            "notes": "",
        },
        follow=True,
    )
    assert b"No backup stock available" in response.content
    assert equipment.accessories.count() == 0


def test_engineer_edits_accessory_via_view(client, engineer, fitted_accessory):
    client.force_login(engineer)
    response = client.post(
        reverse("accessory_edit", args=[fitted_accessory.pk]),
        {"status": "faulty", "serial_number": "", "notes": "Cracked housing."},
    )
    assert response.status_code == 302
    fitted_accessory.refresh_from_db()
    assert fitted_accessory.status == AccessoryStatus.FAULTY


def test_edit_form_rejects_condemned_status(client, engineer, fitted_accessory):
    client.force_login(engineer)
    response = client.post(
        reverse("accessory_edit", args=[fitted_accessory.pk]),
        {"status": "condemned", "serial_number": "", "notes": ""},
    )
    assert response.status_code == 200
    fitted_accessory.refresh_from_db()
    assert fitted_accessory.status == AccessoryStatus.WORKING


def test_engineer_condemns_accessory_via_view(client, engineer, fitted_accessory):
    client.force_login(engineer)
    response = client.post(
        reverse("accessory_condemn", args=[fitted_accessory.pk]),
        {"reason": "Cable snapped"},
    )
    assert response.status_code == 302
    fitted_accessory.refresh_from_db()
    assert fitted_accessory.status == AccessoryStatus.CONDEMNED
    assert fitted_accessory.condemned_at is not None


def test_nav_shows_accessories_link_to_engineer_only(client, engineer, staff_user):
    client.force_login(engineer)
    assert b'href="/equipment/accessories/"' in client.get("/").content
    client.force_login(staff_user)
    assert b'href="/equipment/accessories/"' not in client.get("/").content


def test_type_form_suggests_registered_equipment(client, engineer, equipment):
    client.force_login(engineer)
    content = client.get(reverse("accessory_type_create")).content.decode()
    assert 'list="equipment-name-options"' in content
    assert '<datalist id="equipment-name-options">' in content
    assert "Ventilator Hamilton C2" in content


def test_type_accepts_unlisted_equipment_name(client, engineer):
    client.force_login(engineer)
    response = client.post(
        reverse("accessory_type_create"),
        {
            "name": "ECG cable",
            "equipment_name": "Brand New Device X1",
            "notes": "",
        },
    )
    assert response.status_code == 302
    assert AccessoryType.objects.filter(
        equipment_name="Brand New Device X1"
    ).exists()
