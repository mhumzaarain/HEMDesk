import pytest
from django.core.exceptions import PermissionDenied

from apps.core.exceptions import WorkOrderStateError
from apps.core.models import AuditLog
from apps.equipment.services import condemn_equipment
from apps.maintenance.models import (
    CloseReason,
    Complaint,
    ComplaintStatus,
    FunctionalConfirmation,
)
from apps.maintenance.services import (
    complete_work_order,
    confirm_complaint,
    lodge_complaint,
    open_work_order,
    start_repair,
)

pytestmark = pytest.mark.django_db


def test_complaint_confirmation_fields_default_null(equipment, staff_user):
    c = Complaint.objects.create(
        equipment=equipment, reporter=staff_user, description="x"
    )
    assert c.functional_confirmation is None
    assert c.confirmed_at is None


def test_functional_confirmation_choices():
    assert FunctionalConfirmation.FUNCTIONAL == "functional"
    assert FunctionalConfirmation.NOT_FUNCTIONAL == "not_functional"


def test_awaiting_confirmation_true_after_repair(
    equipment, staff_user, engineer, fault
):
    complaint = lodge_complaint(staff_user, equipment, "broken")
    wo = start_repair(open_work_order(equipment, engineer), engineer)
    complete_work_order(wo, engineer, fault_category=fault("electrical"))
    complaint.refresh_from_db()
    assert complaint.status == ComplaintStatus.CLOSED
    assert complaint.close_reason == CloseReason.RESOLVED
    assert complaint.is_awaiting_confirmation is True


def test_not_awaiting_for_open_complaint(equipment, staff_user):
    complaint = lodge_complaint(staff_user, equipment, "broken")
    assert complaint.is_awaiting_confirmation is False


def test_not_awaiting_after_condemnation(equipment, staff_user, engineer):
    complaint = lodge_complaint(staff_user, equipment, "broken")
    condemn_equipment(equipment, engineer, remark="dead", condemned_location="store")
    complaint.refresh_from_db()
    assert complaint.status == ComplaintStatus.CLOSED
    assert complaint.is_awaiting_confirmation is False


def _resolved_complaint(equipment, staff_user, engineer, fault):
    complaint = lodge_complaint(staff_user, equipment, "broken")
    wo = start_repair(open_work_order(equipment, engineer), engineer)
    complete_work_order(wo, engineer, fault_category=fault("electrical"))
    complaint.refresh_from_db()
    return complaint


def test_reporter_confirms_functional(equipment, staff_user, engineer, fault):
    complaint = _resolved_complaint(equipment, staff_user, engineer, fault)
    confirm_complaint(complaint, staff_user, is_functional=True)
    complaint.refresh_from_db()
    assert complaint.functional_confirmation == FunctionalConfirmation.FUNCTIONAL
    assert complaint.confirmed_at is not None
    assert complaint.is_awaiting_confirmation is False
    assert AuditLog.objects.filter(verb="complaint.confirmed").count() == 1


def test_reporter_confirms_not_functional(equipment, staff_user, engineer, fault):
    complaint = _resolved_complaint(equipment, staff_user, engineer, fault)
    confirm_complaint(complaint, staff_user, is_functional=False)
    complaint.refresh_from_db()
    assert complaint.functional_confirmation == FunctionalConfirmation.NOT_FUNCTIONAL


def test_non_reporter_cannot_confirm(
    equipment, staff_user, engineer, admin_user, fault
):
    complaint = _resolved_complaint(equipment, staff_user, engineer, fault)
    with pytest.raises(PermissionDenied):
        confirm_complaint(complaint, admin_user, is_functional=True)


def test_cannot_confirm_twice(equipment, staff_user, engineer, fault):
    complaint = _resolved_complaint(equipment, staff_user, engineer, fault)
    confirm_complaint(complaint, staff_user, is_functional=True)
    with pytest.raises(WorkOrderStateError):
        confirm_complaint(complaint, staff_user, is_functional=False)
