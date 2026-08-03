import pytest
from django.db.utils import IntegrityError

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
