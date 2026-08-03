import pytest
from django.core.exceptions import PermissionDenied
from django.db.utils import IntegrityError

from apps.core.exceptions import AccessoryStateError
from apps.core.models import AuditLog
from apps.equipment import services
from apps.equipment.models import Accessory, AccessoryStatus, AccessoryType

pytestmark = pytest.mark.django_db


def test_accessory_type_defaults(accessory_type):
    assert accessory_type.stock_qty == 0
    assert str(accessory_type) == "ECG cable — Patient Monitor SVM 7523"


def test_accessory_type_duplicate_rejected(accessory_type):
    with pytest.raises(IntegrityError):
        AccessoryType.objects.create(
            name="ECG cable", equipment_name="Patient Monitor SVM 7523"
        )


def test_accessory_defaults(fitted_accessory):
    assert fitted_accessory.status == AccessoryStatus.WORKING
    assert fitted_accessory.condemned_at is None
    assert fitted_accessory.equipment.accessories.count() == 1
    assert fitted_accessory.type.units.count() == 1


def test_no_hard_delete(accessory_type, fitted_accessory):
    with pytest.raises(TypeError):
        fitted_accessory.delete()
    with pytest.raises(TypeError):
        Accessory.objects.all().delete()
    with pytest.raises(TypeError):
        accessory_type.delete()


def test_staff_cannot_create_type(staff_user):
    with pytest.raises(PermissionDenied):
        services.create_accessory_type(
            staff_user, name="ECG cable", equipment_name="Monitor X"
        )


def test_create_type_writes_audit(engineer):
    accessory_type = services.create_accessory_type(
        engineer, name="NIBP cuff", equipment_name="Patient Monitor SVM 7523"
    )
    assert accessory_type.pk is not None
    assert AuditLog.objects.filter(verb="accessory_type.created").exists()


def test_update_type_records_diff(accessory_type, engineer):
    services.update_accessory_type(
        accessory_type,
        engineer,
        name="ECG cable 5-lead",
        equipment_name=accessory_type.equipment_name,
        notes="",
    )
    entry = AuditLog.objects.get(verb="accessory_type.updated")
    assert entry.changes["name"]["new"] == "ECG cable 5-lead"


def test_staff_cannot_adjust_stock(accessory_type, staff_user):
    with pytest.raises(PermissionDenied):
        services.adjust_stock(accessory_type, staff_user, 1, "sneaky")


def test_adjust_stock_add_and_remove(accessory_type, engineer):
    services.adjust_stock(accessory_type, engineer, 5, "Received shipment")
    accessory_type.refresh_from_db()
    assert accessory_type.stock_qty == 5
    services.adjust_stock(accessory_type, engineer, -2, "Issued to ICU")
    accessory_type.refresh_from_db()
    assert accessory_type.stock_qty == 3
    entry = AuditLog.objects.filter(verb="accessory_type.stock_adjusted").last()
    assert entry.changes == {"delta": -2, "reason": "Issued to ICU", "stock_qty": 3}


def test_stock_cannot_go_negative(accessory_type, engineer):
    with pytest.raises(AccessoryStateError):
        services.adjust_stock(accessory_type, engineer, -1, "oops")
    accessory_type.refresh_from_db()
    assert accessory_type.stock_qty == 0


def test_zero_stock_delta_rejected(accessory_type, engineer):
    with pytest.raises(AccessoryStateError):
        services.adjust_stock(accessory_type, engineer, 0, "noop")
