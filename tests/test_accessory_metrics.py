from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.equipment import services
from apps.reports import metrics

pytestmark = pytest.mark.django_db


@pytest.fixture
def replacement_event(accessory_type, fitted_accessory, engineer, make_work_order):
    services.adjust_stock(accessory_type, engineer, 1, "Initial stock")
    wo = make_work_order()
    return services.replace_accessory(
        fitted_accessory, engineer, wo, remark="worn"
    )


def test_replacements_by_equipment_and_type(replacement_event, equipment):
    end = timezone.now() + timedelta(minutes=1)
    start = end - timedelta(days=90)
    by_eq = metrics.accessory_replacements_by_equipment(start, end)
    assert by_eq[0]["equipment_id"] == equipment.pk
    assert by_eq[0]["n"] == 1
    assert equipment.serial_number in by_eq[0]["label"]
    by_type = metrics.accessory_replacements_by_type(start, end)
    assert by_type[0]["n"] == 1
    assert "ECG cable" in by_type[0]["label"]


def test_window_excludes_old_events(replacement_event):
    end = timezone.now() - timedelta(days=365)
    start = end - timedelta(days=90)
    assert metrics.accessory_replacements_by_equipment(start, end) == []
    assert metrics.accessory_replacements_by_type(start, end) == []


def test_dashboard_panel_renders(client, engineer, replacement_event):
    client.force_login(engineer)
    content = client.get(reverse("dashboard")).content.decode()
    assert "Accessory replacements" in content
    assert "ECG cable" in content


def test_equipment_summary_line(client, engineer, replacement_event, equipment):
    client.force_login(engineer)
    content = client.get(
        reverse("equipment_detail", args=[equipment.pk])
    ).content.decode()
    assert "1 replaced all-time" in content
    assert "1× ECG cable" in content


def test_restock_strip_appears_only_at_zero(client, engineer, accessory_type):
    client.force_login(engineer)
    content = client.get(reverse("accessory_type_list")).content.decode()
    assert "Restock needed" in content
    services.adjust_stock(accessory_type, engineer, 3, "Received shipment")
    content = client.get(reverse("accessory_type_list")).content.decode()
    assert "Restock needed" not in content
