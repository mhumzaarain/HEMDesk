import pytest
from django.contrib.auth import get_user_model

from apps.ai import embeddings as ai_embeddings
from apps.equipment.models import Accessory, AccessoryType, Department, Equipment
from apps.maintenance.models import WorkOrder, WorkOrderStatus


@pytest.fixture(autouse=True)
def fake_embedding_backend(request, monkeypatch):
    """Global constraint: tests never touch the network. The embedding
    backend is down by default; tests that want vectors monkeypatch their
    own fakes (which override this), and tests/test_embeddings.py
    exercises the real client through httpx.MockTransport."""
    if request.fspath.basename == "test_embeddings.py":
        return

    def down(*args, **kwargs):
        raise ai_embeddings.EmbeddingUnavailable("embedding backend disabled in tests")

    monkeypatch.setattr(ai_embeddings, "embed_documents", down)
    monkeypatch.setattr(ai_embeddings, "embed_query", down)


@pytest.fixture
def staff_user(db):
    return get_user_model().objects.create_user(
        username="nurse",
        password="pw",
        employee_id="EMP-001",
        role="staff",
        first_name="Nadia",
        last_name="Khan",
    )


@pytest.fixture
def engineer(db):
    return get_user_model().objects.create_user(
        username="engineer1",
        password="pw",
        employee_id="EMP-100",
        role="engineer",
        first_name="Bilal",
        last_name="Ahmed",
    )


@pytest.fixture
def engineer2(db):
    return get_user_model().objects.create_user(
        username="engineer2",
        password="pw",
        employee_id="EMP-101",
        role="engineer",
    )


@pytest.fixture
def admin_user(db):
    return get_user_model().objects.create_user(
        username="boss",
        password="pw",
        employee_id="EMP-900",
        role="admin",
    )


@pytest.fixture
def department(db):
    return Department.objects.create(name="ICU", location="Block A")


@pytest.fixture
def department2(db):
    return Department.objects.create(name="Radiology", location="Block B")


@pytest.fixture
def make_equipment(department):
    def _make(**overrides):
        fields = dict(
            name="Ventilator",
            manufacturer="Hamilton",
            vendor="MedServe Ltd",
            model_number="C2",
            serial_number="SN-0001",
            department=department,
        )
        fields.update(overrides)
        return Equipment.objects.create(**fields)

    return _make


@pytest.fixture
def equipment(make_equipment):
    return make_equipment()


@pytest.fixture
def make_work_order(equipment, engineer):
    def _make(eq=None, **overrides):
        fields = dict(
            equipment=eq or equipment,
            status=WorkOrderStatus.OPEN,
            opened_by=engineer,
        )
        fields.update(overrides)
        return WorkOrder.objects.create(**fields)

    return _make


@pytest.fixture
def accessory_type(db):
    return AccessoryType.objects.create(
        name="ECG cable", equipment_name="Patient Monitor SVM 7523"
    )


@pytest.fixture
def fitted_accessory(accessory_type, equipment):
    return Accessory.objects.create(type=accessory_type, equipment=equipment)
