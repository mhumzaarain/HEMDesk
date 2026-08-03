import pytest
from django.urls import reverse

from apps.equipment import services
from apps.equipment.models import (
    AccessoryEvent,
    AccessoryEventKind,
    AccessoryStatus,
)
from apps.maintenance.models import WorkOrderStatus

pytestmark = pytest.mark.django_db


def test_staff_403_on_wo_accessory_urls(
    client, staff_user, fitted_accessory, make_work_order
):
    wo = make_work_order()
    client.force_login(staff_user)
    post_url = reverse(
        "accessory_mark_faulty", args=[fitted_accessory.pk, wo.pk]
    )
    assert client.post(post_url).status_code == 403
    for name in ("accessory_repair", "accessory_replace"):
        url = reverse(name, args=[fitted_accessory.pk, wo.pk])
        assert client.get(url).status_code == 403


def test_wo_page_shows_buttons_only_while_active(
    client, engineer, fitted_accessory, make_work_order
):
    wo = make_work_order()
    client.force_login(engineer)
    content = client.get(
        reverse("workorder_detail", args=[wo.pk])
    ).content.decode()
    assert "Mark faulty" in content
    assert "Replace…" in content
    done = make_work_order(status=WorkOrderStatus.COMPLETED)
    content = client.get(
        reverse("workorder_detail", args=[done.pk])
    ).content.decode()
    assert "Mark faulty" not in content
    assert "Replace…" not in content


def test_mark_faulty_then_repair_button_appears(
    client, engineer, fitted_accessory, make_work_order
):
    wo = make_work_order()
    client.force_login(engineer)
    response = client.post(
        reverse("accessory_mark_faulty", args=[fitted_accessory.pk, wo.pk])
    )
    assert response.status_code == 302
    fitted_accessory.refresh_from_db()
    assert fitted_accessory.status == AccessoryStatus.FAULTY
    content = client.get(
        reverse("workorder_detail", args=[wo.pk])
    ).content.decode()
    assert ">Repair<" in content


def test_replace_via_ui(
    client, engineer, accessory_type, fitted_accessory, equipment, make_work_order
):
    services.adjust_stock(accessory_type, engineer, 1, "Initial stock")
    wo = make_work_order()
    client.force_login(engineer)
    url = reverse("accessory_replace", args=[fitted_accessory.pk, wo.pk])
    assert client.get(url).status_code == 200
    response = client.post(url, {"remark": "sensor dead", "serial_number": "A-9"})
    assert response.status_code == 302
    accessory_type.refresh_from_db()
    assert accessory_type.stock_qty == 0
    assert equipment.accessories.count() == 2
    event = AccessoryEvent.objects.get(kind=AccessoryEventKind.REPLACED)
    assert event.work_order_id == wo.pk
    content = client.get(
        reverse("workorder_detail", args=[wo.pk])
    ).content.decode()
    assert "sensor dead" in content


def test_replace_without_stock_shows_error(
    client, engineer, fitted_accessory, make_work_order
):
    wo = make_work_order()
    client.force_login(engineer)
    response = client.post(
        reverse("accessory_replace", args=[fitted_accessory.pk, wo.pk]),
        {"remark": "dead", "serial_number": ""},
        follow=True,
    )
    assert b"No backup stock available" in response.content
    assert AccessoryEvent.objects.count() == 0


def test_repair_via_ui(client, engineer, fitted_accessory, make_work_order):
    services.update_accessory(
        fitted_accessory, engineer, status=AccessoryStatus.FAULTY
    )
    wo = make_work_order()
    client.force_login(engineer)
    response = client.post(
        reverse("accessory_repair", args=[fitted_accessory.pk, wo.pk]),
        {"remark": "re-soldered connector"},
    )
    assert response.status_code == 302
    fitted_accessory.refresh_from_db()
    assert fitted_accessory.status == AccessoryStatus.WORKING
    assert (
        AccessoryEvent.objects.filter(kind=AccessoryEventKind.REPAIRED).count()
        == 1
    )
