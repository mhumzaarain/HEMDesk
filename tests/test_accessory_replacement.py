import pytest
from django.core.exceptions import PermissionDenied

from apps.core.exceptions import AccessoryStateError
from apps.core.models import AuditLog
from apps.equipment import services
from apps.equipment.models import AccessoryEvent, AccessoryEventKind, AccessoryStatus
from apps.maintenance.models import WorkOrderStatus

pytestmark = pytest.mark.django_db


def test_accessory_event_append_only(fitted_accessory, engineer, make_work_order):
    wo = make_work_order()
    event = AccessoryEvent.objects.create(
        kind=AccessoryEventKind.REPAIRED,
        work_order=wo,
        equipment=fitted_accessory.equipment,
        accessory_type=fitted_accessory.type,
        old_accessory=fitted_accessory,
        actor=engineer,
    )
    assert event.new_accessory is None
    with pytest.raises(TypeError):
        event.save()
    with pytest.raises(TypeError):
        event.delete()
    with pytest.raises(TypeError):
        AccessoryEvent.objects.all().delete()


def test_accessory_event_related_names(fitted_accessory, engineer, make_work_order):
    wo = make_work_order()
    AccessoryEvent.objects.create(
        kind=AccessoryEventKind.REPAIRED,
        work_order=wo,
        equipment=fitted_accessory.equipment,
        accessory_type=fitted_accessory.type,
        old_accessory=fitted_accessory,
        actor=engineer,
    )
    assert wo.accessory_events.count() == 1
    assert fitted_accessory.equipment.accessory_events.count() == 1
    assert fitted_accessory.type.events.count() == 1
    assert fitted_accessory.events_as_old.count() == 1


def test_replace_swaps_unit_stock_and_event(
    accessory_type, fitted_accessory, equipment, engineer, make_work_order
):
    services.adjust_stock(accessory_type, engineer, 2, "Initial stock")
    wo = make_work_order()
    event = services.replace_accessory(
        fitted_accessory, engineer, wo, remark="sensor dead", serial_number="ACC-9"
    )
    fitted_accessory.refresh_from_db()
    accessory_type.refresh_from_db()
    assert fitted_accessory.status == AccessoryStatus.CONDEMNED
    assert fitted_accessory.condemned_at is not None
    assert accessory_type.stock_qty == 1
    new = equipment.accessories.exclude(pk=fitted_accessory.pk).get()
    assert new.status == AccessoryStatus.WORKING
    assert new.serial_number == "ACC-9"
    assert event.kind == AccessoryEventKind.REPLACED
    assert event.old_accessory == fitted_accessory
    assert event.new_accessory == new
    assert event.work_order == wo
    assert AuditLog.objects.filter(verb="accessory.replaced").exists()
    stock_entry = (
        AuditLog.objects.filter(verb="accessory_type.stock_adjusted")
        .order_by("created_at")
        .last()
    )
    assert stock_entry.changes["reason"] == f"Replacement on WO #{wo.pk}"


def test_replace_refused_without_stock(
    fitted_accessory, equipment, engineer, make_work_order
):
    wo = make_work_order()
    with pytest.raises(AccessoryStateError):
        services.replace_accessory(fitted_accessory, engineer, wo, remark="dead")
    fitted_accessory.refresh_from_db()
    assert fitted_accessory.status == AccessoryStatus.WORKING
    assert equipment.accessories.count() == 1
    assert AccessoryEvent.objects.count() == 0


def test_replace_refused_on_inactive_workorder(
    accessory_type, fitted_accessory, engineer, make_work_order
):
    services.adjust_stock(accessory_type, engineer, 1, "Initial stock")
    wo = make_work_order(status=WorkOrderStatus.COMPLETED)
    with pytest.raises(AccessoryStateError):
        services.replace_accessory(fitted_accessory, engineer, wo, remark="dead")


def test_replace_refused_for_other_equipment(
    accessory_type, fitted_accessory, engineer, make_equipment, make_work_order
):
    services.adjust_stock(accessory_type, engineer, 1, "Initial stock")
    other = make_equipment(serial_number="SN-0002")
    wo = make_work_order(eq=other)
    with pytest.raises(AccessoryStateError):
        services.replace_accessory(fitted_accessory, engineer, wo, remark="dead")


def test_replace_refused_when_condemned(
    accessory_type, fitted_accessory, engineer, make_work_order
):
    services.adjust_stock(accessory_type, engineer, 1, "Initial stock")
    services.condemn_accessory(fitted_accessory, engineer, "scrapped")
    wo = make_work_order()
    with pytest.raises(AccessoryStateError):
        services.replace_accessory(fitted_accessory, engineer, wo, remark="dead")


def test_staff_cannot_replace_or_repair(
    fitted_accessory, staff_user, make_work_order
):
    wo = make_work_order()
    with pytest.raises(PermissionDenied):
        services.replace_accessory(fitted_accessory, staff_user, wo, remark="x")
    with pytest.raises(PermissionDenied):
        services.repair_accessory(fitted_accessory, staff_user, wo, remark="x")


def test_repair_flips_faulty_and_logs_event(
    fitted_accessory, engineer, make_work_order
):
    services.update_accessory(
        fitted_accessory, engineer, status=AccessoryStatus.FAULTY
    )
    wo = make_work_order()
    event = services.repair_accessory(
        fitted_accessory, engineer, wo, remark="re-soldered connector"
    )
    fitted_accessory.refresh_from_db()
    assert fitted_accessory.status == AccessoryStatus.WORKING
    assert event.kind == AccessoryEventKind.REPAIRED
    assert event.new_accessory is None
    assert AuditLog.objects.filter(verb="accessory.repaired").exists()


def test_repair_requires_faulty(fitted_accessory, engineer, make_work_order):
    wo = make_work_order()
    with pytest.raises(AccessoryStateError):
        services.repair_accessory(fitted_accessory, engineer, wo, remark="x")


def test_repair_refused_on_inactive_workorder(
    fitted_accessory, engineer, make_work_order
):
    services.update_accessory(
        fitted_accessory, engineer, status=AccessoryStatus.FAULTY
    )
    wo = make_work_order(status=WorkOrderStatus.CANCELLED)
    with pytest.raises(AccessoryStateError):
        services.repair_accessory(fitted_accessory, engineer, wo, remark="x")
