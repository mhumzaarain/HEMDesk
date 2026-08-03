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


class TestPPMCompleteView:
    def test_get_renders_form(self, client, engineer, schedule):
        client.force_login(engineer)
        resp = client.get(reverse("ppm_complete", args=[schedule.pk]))
        assert resp.status_code == 200
        assert b"outcome" in resp.content

    def test_post_passed_records_and_redirects(self, client, engineer, schedule):
        client.force_login(engineer)
        resp = client.post(
            reverse("ppm_complete", args=[schedule.pk]),
            {
                "performed_at": timezone.localdate().isoformat(),
                "outcome": "passed",
                "remarks": "Battery and alarms OK.",
            },
        )
        assert resp.status_code == 302
        record = schedule.records.get()
        assert record.outcome == "passed"
        schedule.refresh_from_db()
        assert schedule.next_due > timezone.localdate()

    def test_post_failed_with_open_wo_links_work_order(
        self, client, engineer, schedule
    ):
        client.force_login(engineer)
        resp = client.post(
            reverse("ppm_complete", args=[schedule.pk]),
            {
                "performed_at": timezone.localdate().isoformat(),
                "outcome": "failed",
                "open_work_order": "on",
            },
        )
        assert resp.status_code == 302
        record = schedule.records.get()
        assert record.work_order is not None

    def test_open_wo_with_passed_outcome_rejected_by_form(
        self, client, engineer, schedule
    ):
        client.force_login(engineer)
        resp = client.post(
            reverse("ppm_complete", args=[schedule.pk]),
            {
                "performed_at": timezone.localdate().isoformat(),
                "outcome": "passed",
                "open_work_order": "on",
            },
        )
        assert resp.status_code == 200  # re-rendered with form error
        assert schedule.records.count() == 0

    def test_blocked_when_wo_active_shows_error(
        self, client, engineer, schedule, make_work_order
    ):
        make_work_order(eq=schedule.equipment)
        client.force_login(engineer)
        resp = client.post(
            reverse("ppm_complete", args=[schedule.pk]),
            {
                "performed_at": timezone.localdate().isoformat(),
                "outcome": "passed",
            },
            follow=True,
        )
        assert b"under repair" in resp.content
        assert schedule.records.count() == 0

    def test_staff_blocked(self, client, staff_user, schedule):
        client.force_login(staff_user)
        resp = client.get(reverse("ppm_complete", args=[schedule.pk]))
        assert resp.status_code == 403


class TestDueListView:
    @pytest.fixture
    def three_schedules(self, make_equipment, engineer, department2):
        today = timezone.localdate()
        overdue_eq = make_equipment(serial_number="SN-PPM-1")
        soon_eq = make_equipment(serial_number="SN-PPM-2", department=department2)
        later_eq = make_equipment(serial_number="SN-PPM-3")
        s1 = services.set_ppm_schedule(
            overdue_eq, engineer, PPMInterval.MONTHLY, today - timedelta(days=5)
        )
        s2 = services.set_ppm_schedule(
            soon_eq, engineer, PPMInterval.MONTHLY, today + timedelta(days=10)
        )
        s3 = services.set_ppm_schedule(
            later_eq, engineer, PPMInterval.ANNUAL, today + timedelta(days=200)
        )
        return s1, s2, s3

    def test_buckets(self, client, engineer, three_schedules):
        client.force_login(engineer)
        resp = client.get(reverse("ppm_due_list"))
        assert resp.status_code == 200
        overdue = [s.pk for s in resp.context["overdue"]]
        due_soon = [s.pk for s in resp.context["due_soon"]]
        s1, s2, s3 = three_schedules
        assert overdue == [s1.pk]
        assert due_soon == [s2.pk]
        assert s3.pk not in overdue + due_soon

    def test_department_filter(self, client, engineer, three_schedules, department2):
        client.force_login(engineer)
        resp = client.get(
            reverse("ppm_due_list"), {"department": str(department2.pk)}
        )
        s1, s2, s3 = three_schedules
        assert [s.pk for s in resp.context["due_soon"]] == [s2.pk]
        assert list(resp.context["overdue"]) == []

    def test_inactive_schedules_hidden(self, client, engineer, three_schedules):
        s1, _, _ = three_schedules
        services.set_ppm_schedule(
            s1.equipment, engineer, s1.interval, s1.next_due, active=False
        )
        client.force_login(engineer)
        resp = client.get(reverse("ppm_due_list"))
        assert list(resp.context["overdue"]) == []

    def test_unscheduled_count(self, client, engineer, three_schedules, equipment):
        # `equipment` fixture device has no schedule
        client.force_login(engineer)
        resp = client.get(reverse("ppm_due_list"))
        assert resp.context["unscheduled_count"] == 1

    def test_staff_blocked(self, client, staff_user):
        client.force_login(staff_user)
        assert client.get(reverse("ppm_due_list")).status_code == 403
