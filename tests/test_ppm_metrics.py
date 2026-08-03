from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.maintenance import services
from apps.maintenance.models import PPMInterval
from apps.reports import metrics


@pytest.fixture
def schedules(make_equipment, engineer, department, department2):
    today = timezone.localdate()
    a = make_equipment(serial_number="SN-M-1")  # department (ICU)
    b = make_equipment(serial_number="SN-M-2", department=department2)
    c = make_equipment(serial_number="SN-M-3", department=department2)
    services.set_ppm_schedule(
        a, engineer, PPMInterval.MONTHLY, today - timedelta(days=3)
    )
    services.set_ppm_schedule(
        b, engineer, PPMInterval.MONTHLY, today - timedelta(days=1)
    )
    services.set_ppm_schedule(
        c, engineer, PPMInterval.MONTHLY, today + timedelta(days=7)
    )


def test_ppm_due_counts(schedules):
    counts = metrics.ppm_due_counts()
    assert counts == {"overdue": 2, "due_soon": 1}


def test_ppm_due_counts_empty(db):
    assert metrics.ppm_due_counts() == {"overdue": 0, "due_soon": 0}


def test_ppm_overdue_by_department(schedules):
    rows = metrics.ppm_overdue_by_department()
    assert rows == {"ICU": 1, "Radiology": 1}


def test_dashboard_includes_ppm_panel(client, admin_user, schedules):
    client.force_login(admin_user)
    resp = client.get(reverse("dashboard"))
    assert resp.status_code == 200
    assert b"PPM compliance" in resp.content
    assert resp.context["ppm"] == {"overdue": 2, "due_soon": 1}
