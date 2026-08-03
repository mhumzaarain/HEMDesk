import pytest
from django.core.exceptions import PermissionDenied
from django.db.utils import IntegrityError

from apps.core.exceptions import AccessoryStateError
from apps.core.models import AuditLog
from apps.equipment import services
from apps.equipment.models import (
    Accessory,
    AccessoryStatus,
    AccessoryType,
    EquipmentStatus,
)

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
    entry = (
        AuditLog.objects.filter(verb="accessory_type.stock_adjusted")
        .order_by("created_at")
        .last()
    )
    assert entry.changes == {"delta": -2, "reason": "Issued to ICU", "stock_qty": 3}


def test_stock_cannot_go_negative(accessory_type, engineer):
    with pytest.raises(AccessoryStateError):
        services.adjust_stock(accessory_type, engineer, -1, "oops")
    accessory_type.refresh_from_db()
    assert accessory_type.stock_qty == 0


def test_zero_stock_delta_rejected(accessory_type, engineer):
    with pytest.raises(AccessoryStateError):
        services.adjust_stock(accessory_type, engineer, 0, "noop")


def test_staff_cannot_attach(accessory_type, equipment, staff_user):
    with pytest.raises(PermissionDenied):
        services.attach_accessory(
            equipment, staff_user, accessory_type, from_stock=False
        )


def test_attach_from_stock_decrements(accessory_type, equipment, engineer):
    services.adjust_stock(accessory_type, engineer, 2, "Initial stock")
    accessory = services.attach_accessory(
        equipment, engineer, accessory_type, from_stock=True
    )
    accessory_type.refresh_from_db()
    assert accessory_type.stock_qty == 1
    assert accessory.equipment == equipment
    assert AuditLog.objects.filter(verb="accessory.attached").exists()


def test_attach_refused_when_stock_empty(accessory_type, equipment, engineer):
    with pytest.raises(AccessoryStateError):
        services.attach_accessory(
            equipment, engineer, accessory_type, from_stock=True
        )
    assert equipment.accessories.count() == 0


def test_attach_without_stock_keeps_counter(accessory_type, equipment, engineer):
    services.attach_accessory(equipment, engineer, accessory_type, from_stock=False)
    accessory_type.refresh_from_db()
    assert accessory_type.stock_qty == 0
    assert equipment.accessories.count() == 1


def test_attach_refused_on_condemned_equipment(
    accessory_type, make_equipment, engineer
):
    condemned = make_equipment(
        serial_number="SN-0009", status=EquipmentStatus.CONDEMNED
    )
    with pytest.raises(AccessoryStateError):
        services.attach_accessory(
            condemned, engineer, accessory_type, from_stock=False
        )


def test_update_accessory_diff_audited(fitted_accessory, engineer):
    services.update_accessory(
        fitted_accessory, engineer, status=AccessoryStatus.FAULTY, notes="No signal."
    )
    fitted_accessory.refresh_from_db()
    assert fitted_accessory.status == AccessoryStatus.FAULTY
    entry = AuditLog.objects.get(verb="accessory.updated")
    assert entry.changes["status"]["new"] == "faulty"


def test_condemn_accessory_stamps_and_locks(fitted_accessory, engineer):
    services.condemn_accessory(fitted_accessory, engineer, "Cable snapped")
    fitted_accessory.refresh_from_db()
    assert fitted_accessory.status == AccessoryStatus.CONDEMNED
    assert fitted_accessory.condemned_at is not None
    assert AuditLog.objects.filter(verb="accessory.condemned").exists()
    with pytest.raises(AccessoryStateError):
        services.update_accessory(fitted_accessory, engineer, notes="too late")
    with pytest.raises(AccessoryStateError):
        services.condemn_accessory(fitted_accessory, engineer, "again")


def test_update_refused_on_condemned_equipment(
    fitted_accessory, equipment, engineer
):
    equipment.status = EquipmentStatus.CONDEMNED
    equipment.save(update_fields=["status"])
    with pytest.raises(AccessoryStateError):
        services.update_accessory(fitted_accessory, engineer, notes="x")


def test_update_type_cannot_touch_stock(accessory_type, engineer):
    with pytest.raises(AccessoryStateError):
        services.update_accessory_type(accessory_type, engineer, stock_qty=999)
    accessory_type.refresh_from_db()
    assert accessory_type.stock_qty == 0


def test_update_accessory_cannot_set_condemned(fitted_accessory, engineer):
    with pytest.raises(AccessoryStateError):
        services.update_accessory(
            fitted_accessory, engineer, status=AccessoryStatus.CONDEMNED
        )
    fitted_accessory.refresh_from_db()
    assert fitted_accessory.status == AccessoryStatus.WORKING
