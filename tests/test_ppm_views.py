from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.maintenance import services
from apps.maintenance.models import PPMInterval, PPMSchedule


@pytest.fixture
def schedule(equipment, engineer):
    return services.set_ppm_schedule(
        equipment, engineer, PPMInterval.QUARTERLY, timezone.localdate()
    )


class TestScheduleEditView:
    def test_get_renders_form(self, client, engineer, equipment):
        client.force_login(engineer)
        resp = client.get(reverse("ppm_schedule_edit", args=[equipment.pk]))
        assert resp.status_code == 200
        assert b"interval" in resp.content

    def test_post_creates_schedule(self, client, engineer, equipment):
        client.force_login(engineer)
        due = timezone.localdate() + timedelta(days=14)
        resp = client.post(
            reverse("ppm_schedule_edit", args=[equipment.pk]),
            {"interval": "monthly", "next_due": due.isoformat(), "active": "on"},
        )
        assert resp.status_code == 302
        schedule = PPMSchedule.objects.get(equipment=equipment)
        assert schedule.interval == PPMInterval.MONTHLY
        assert schedule.next_due == due

    def test_staff_blocked(self, client, staff_user, equipment):
        client.force_login(staff_user)
        resp = client.get(reverse("ppm_schedule_edit", args=[equipment.pk]))
        assert resp.status_code == 403


class TestEquipmentDetailPanel:
    def test_detail_shows_schedule(self, client, engineer, schedule):
        client.force_login(engineer)
        resp = client.get(
            reverse("equipment_detail", args=[schedule.equipment.pk])
        )
        assert resp.status_code == 200
        assert b"Preventive Maintenance" in resp.content
        assert b"Quarterly" in resp.content

    def test_detail_without_schedule_offers_setup(self, client, engineer, equipment):
        client.force_login(engineer)
        resp = client.get(reverse("equipment_detail", args=[equipment.pk]))
        assert b"No PPM schedule" in resp.content
        assert b"Set schedule" in resp.content

    def test_staff_sees_panel_without_buttons(self, client, staff_user, schedule):
        client.force_login(staff_user)
        resp = client.get(
            reverse("equipment_detail", args=[schedule.equipment.pk])
        )
        assert b"Preventive Maintenance" in resp.content
        assert b"Set schedule" not in resp.content
