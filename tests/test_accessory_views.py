import pytest
from django.urls import reverse

from apps.equipment.models import AccessoryType

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
