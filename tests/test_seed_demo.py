import pytest
from django.core.management import call_command

from apps.core.models import AuditLog
from apps.equipment.models import (
    Accessory,
    AccessoryStatus,
    AccessoryType,
    Equipment,
    EquipmentStatus,
    StatusEvent,
)
from apps.maintenance.models import Complaint, WorkOrder

pytestmark = pytest.mark.django_db


def test_seed_demo_builds_world():
    call_command("seed_demo")
    assert Equipment.objects.count() >= 50
    assert Equipment.objects.filter(is_critical_asset=True).count() >= 4
    assert Equipment.objects.filter(status=EquipmentStatus.CONDEMNED).count() >= 2
    assert Complaint.objects.count() >= 40
    assert AccessoryType.objects.count() == 6
    assert not AccessoryType.objects.filter(stock_qty=0).exists()
    assert Accessory.objects.count() >= 10
    assert Accessory.objects.filter(status=AccessoryStatus.FAULTY).count() == 1
    assert WorkOrder.objects.filter(status="completed").count() >= 20
    assert StatusEvent.objects.count() > 0
    assert AuditLog.objects.count() > 0
    # history is spread over time, not all "now"
    first = Complaint.objects.order_by("created_at").first()
    last = Complaint.objects.order_by("created_at").last()
    assert (last.created_at - first.created_at).days > 30


def test_seed_demo_refuses_to_run_twice():
    call_command("seed_demo")
    with pytest.raises(SystemExit):
        call_command("seed_demo")
