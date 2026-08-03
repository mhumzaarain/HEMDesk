import pytest

from apps.equipment.models import AccessoryEvent, AccessoryEventKind

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
