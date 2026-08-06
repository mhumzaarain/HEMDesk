import pytest
from django.urls import reverse

from apps.maintenance.models import (
    CloseReason,
    Complaint,
    ComplaintStatus,
    WorkOrderStatus,
)
from apps.maintenance.services import lodge_complaint, open_work_order, start_repair

pytestmark = pytest.mark.django_db


def test_staff_lodges_complaint_via_form(client, staff_user, equipment):
    client.force_login(staff_user)
    response = client.post(
        reverse("complaint_new"),
        {
            "equipment": equipment.pk,
            "description": "Screen flickers then dies",
        },
    )
    assert response.status_code == 302
    complaint = Complaint.objects.get()
    assert complaint.reporter == staff_user
    assert complaint.equipment == equipment


def test_lodge_blocked_for_in_repair_shows_error(
    client, staff_user, equipment, engineer
):
    start_repair(open_work_order(equipment, engineer), engineer)
    client.force_login(staff_user)
    response = client.post(
        reverse("complaint_new"),
        {
            "equipment": equipment.pk,
            "description": "still broken",
        },
        follow=True,
    )
    assert b"already under repair" in response.content
    assert Complaint.objects.count() == 0


def test_queue_requires_engineer(client, staff_user):
    client.force_login(staff_user)
    assert client.get(reverse("complaint_queue")).status_code == 403


def test_queue_rows_partial_lists_open_complaints(
    client, engineer, staff_user, equipment
):
    lodge_complaint(staff_user, equipment, "no power at all")
    client.force_login(engineer)
    response = client.get(reverse("complaint_queue_rows"))
    assert b"no power at all" in response.content
    assert b"SN-0001" in response.content


def test_close_duplicate_via_view(client, engineer, staff_user, equipment):
    first = lodge_complaint(staff_user, equipment, "display broken")
    second = lodge_complaint(staff_user, equipment, "screen dead")
    client.force_login(engineer)
    response = client.post(
        reverse("complaint_close", args=[second.pk]),
        {
            "close_reason": CloseReason.DUPLICATE,
            "duplicate_of": first.pk,
            "close_note": "same fault, reported twice",
        },
    )
    assert response.status_code == 302
    second.refresh_from_db()
    assert second.status == ComplaintStatus.CLOSED
    assert second.duplicate_of == first


def test_open_start_complete_workorder_via_views(
    client, engineer, staff_user, equipment, fault
):
    complaint = lodge_complaint(staff_user, equipment, "won't switch on")
    client.force_login(engineer)
    r = client.post(reverse("workorder_open", args=[equipment.pk]))
    assert r.status_code == 302
    wo = equipment.work_orders.get()
    client.post(reverse("workorder_start", args=[wo.pk]))
    wo.refresh_from_db()
    assert wo.status == WorkOrderStatus.IN_PROGRESS
    r = client.post(
        reverse("workorder_complete", args=[wo.pk]),
        {
            "fault_category": fault("electrical").pk,
            "participants": [],
            "remark": "fuse replaced",
        },
    )
    assert r.status_code == 302
    wo.refresh_from_db()
    complaint.refresh_from_db()
    assert wo.status == WorkOrderStatus.COMPLETED
    assert complaint.status == ComplaintStatus.CLOSED


def test_delay_remark_via_view(client, engineer, equipment):
    wo = open_work_order(equipment, engineer)
    client.force_login(engineer)
    client.post(
        reverse("workorder_remark", args=[wo.pk]),
        {
            "text": "waiting for vendor part",
            "kind": "delay",
        },
    )
    assert wo.remarks.filter(kind="delay").exists()


def test_join_workorder(client, engineer, engineer2, equipment):
    wo = open_work_order(equipment, engineer)
    client.force_login(engineer2)
    client.post(reverse("workorder_join", args=[wo.pk]))
    assert engineer2 in wo.participants.all()


def test_home_shows_landing_page(client, staff_user):
    client.force_login(staff_user)
    response = client.get(reverse("home"))
    assert response.status_code == 200
    assert b"Report a fault" in response.content
    assert b"Browse equipment" in response.content


def test_staff_confirms_via_view(client, staff_user, engineer, equipment, fault):
    from apps.maintenance.models import FunctionalConfirmation
    from apps.maintenance.services import (
        complete_work_order,
        lodge_complaint,
        open_work_order,
        start_repair,
    )

    complaint = lodge_complaint(staff_user, equipment, "no power")
    wo = start_repair(open_work_order(equipment, engineer), engineer)
    complete_work_order(wo, engineer, fault_category=fault("electrical"))
    client.force_login(staff_user)
    response = client.post(
        reverse("complaint_confirm", args=[complaint.pk]), {"functional": "yes"}
    )
    assert response.status_code == 302
    complaint.refresh_from_db()
    assert complaint.functional_confirmation == FunctionalConfirmation.FUNCTIONAL


def test_my_complaints_shows_confirm_prompt(
    client, staff_user, engineer, equipment, fault
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
    client.force_login(staff_user)
    response = client.get(reverse("my_complaints"))
    assert b"functional now" in response.content


def test_other_staff_cannot_confirm(client, staff_user, engineer, equipment, fault):
    from django.contrib.auth import get_user_model

    from apps.maintenance.services import (
        complete_work_order,
        lodge_complaint,
        open_work_order,
        start_repair,
    )

    complaint = lodge_complaint(staff_user, equipment, "no power")
    wo = start_repair(open_work_order(equipment, engineer), engineer)
    complete_work_order(wo, engineer, fault_category=fault("electrical"))
    other = get_user_model().objects.create_user(
        username="nurse2", password="pw", employee_id="EMP-002", role="staff"
    )
    client.force_login(other)
    assert (
        client.post(
            reverse("complaint_confirm", args=[complaint.pk]), {"functional": "yes"}
        ).status_code
        == 403
    )


def test_workorder_detail_forbidden_for_staff(client, staff_user, engineer, equipment):
    from apps.maintenance.services import open_work_order

    wo = open_work_order(equipment, engineer)
    client.force_login(staff_user)
    assert client.get(reverse("workorder_detail", args=[wo.pk])).status_code == 403


def test_workorder_detail_shows_confirmation(
    client, engineer, staff_user, equipment, fault
):
    from apps.maintenance.services import (
        complete_work_order,
        confirm_complaint,
        lodge_complaint,
        open_work_order,
        start_repair,
    )

    complaint = lodge_complaint(staff_user, equipment, "no power")
    wo = start_repair(open_work_order(equipment, engineer), engineer)
    complete_work_order(wo, engineer, fault_category=fault("electrical"))
    complaint.refresh_from_db()
    confirm_complaint(complaint, staff_user, is_functional=False)
    client.force_login(engineer)
    response = client.get(reverse("workorder_detail", args=[wo.pk]))
    assert b"NOT functional" in response.content
