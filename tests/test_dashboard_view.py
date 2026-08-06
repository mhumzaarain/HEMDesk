import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_dashboard_requires_engineer(client, staff_user):
    client.force_login(staff_user)
    assert client.get(reverse("dashboard")).status_code == 403


def test_dashboard_renders_for_engineer(client, engineer):
    client.force_login(engineer)
    response = client.get(reverse("dashboard"))
    assert response.status_code == 200
    assert b"chart.umd.js" in response.content


def test_dashboard_shows_complaints_resolved(
    client, engineer, staff_user, equipment, fault
):
    from apps.maintenance.services import (
        complete_work_order,
        lodge_complaint,
        open_work_order,
        start_repair,
    )

    lodge_complaint(staff_user, equipment, "no power")
    wo = start_repair(open_work_order(equipment, engineer), engineer)
    complete_work_order(wo, engineer, fault_category=fault("electrical"))
    client.force_login(engineer)
    response = client.get(reverse("dashboard"))
    assert response.status_code == 200
    assert b"Complaints resolved" in response.content


def test_drilldown_requires_engineer(client, staff_user, engineer):
    client.force_login(staff_user)
    assert (
        client.get(reverse("engineer_resolved", args=[engineer.pk])).status_code == 403
    )


def test_drilldown_lists_resolved(client, engineer, staff_user, equipment, fault):
    from apps.maintenance.services import (
        complete_work_order,
        lodge_complaint,
        open_work_order,
        start_repair,
    )

    lodge_complaint(staff_user, equipment, "no power")
    wo = start_repair(open_work_order(equipment, engineer), engineer)
    complete_work_order(wo, engineer, fault_category=fault("electrical"))
    client.force_login(engineer)
    response = client.get(reverse("engineer_resolved", args=[engineer.pk]))
    assert response.status_code == 200
    assert b"SN-0001" in response.content
