import pytest
from django.urls import reverse

from apps.ai.models import AssistantMessage


@pytest.fixture
def engineer_client(client, engineer):
    client.force_login(engineer)
    return client


def test_staff_blocked(client, staff_user, equipment):
    client.force_login(staff_user)
    url = reverse("assistant_messages", args=[equipment.pk])
    assert client.get(url).status_code == 403


def test_send_creates_message_and_defers(
    engineer_client, engineer, equipment, make_work_order, monkeypatch
):
    deferred = []
    from apps.ai import tasks

    monkeypatch.setattr(
        tasks.answer_assistant_chat, "defer", lambda **kw: deferred.append(kw)
    )
    wo = make_work_order()
    url = reverse("assistant_send", args=[equipment.pk]) + f"?wo={wo.pk}"
    response = engineer_client.post(url, {"content": "no oxygen error"})
    assert response.status_code == 200
    message = AssistantMessage.objects.get()
    assert message.role == "user" and message.work_order == wo
    assert deferred == [{"message_id": message.id, "fault_category": None}]
    assert b"no oxygen error" in response.content


def test_poll_shows_thinking_until_answer(engineer_client, engineer, equipment):
    AssistantMessage.objects.create(
        equipment=equipment, user=engineer, role="user", content="hi"
    )
    url = reverse("assistant_messages", args=[equipment.pk])
    assert b"thinking" in engineer_client.get(url).content.lower()
    AssistantMessage.objects.create(
        equipment=equipment, user=engineer, role="assistant", content="Answer."
    )
    body = engineer_client.get(url).content
    assert b"Answer." in body and b"Advisory only" in body


def test_send_passes_fault_category_to_task(
    engineer_client, engineer, equipment, monkeypatch
):
    from apps.ai import tasks

    captured = {}
    monkeypatch.setattr(
        tasks.answer_assistant_chat, "defer", lambda **kw: captured.update(kw)
    )
    url = reverse("assistant_send", args=[equipment.pk])
    engineer_client.post(
        url,
        {"content": "screen dark", "fault_category": "display_monitor"},
    )
    assert captured["fault_category"] == "display_monitor"


def test_send_drops_unknown_fault_category(
    engineer_client, engineer, equipment, monkeypatch
):
    from apps.ai import tasks

    captured = {}
    monkeypatch.setattr(
        tasks.answer_assistant_chat, "defer", lambda **kw: captured.update(kw)
    )
    url = reverse("assistant_send", args=[equipment.pk])
    engineer_client.post(
        url,
        {"content": "screen dark", "fault_category": "bogus"},
    )
    assert captured["fault_category"] is None


def test_panel_dropdown_covers_all_fault_categories(
    engineer_client, engineer, equipment
):
    from apps.maintenance.models import FaultCategory

    url = reverse("equipment_detail", args=[equipment.pk])
    response = engineer_client.get(url)
    html = response.content.decode()
    assert 'name="fault_category"' in html
    for value in FaultCategory.values:
        assert f'value="{value}"' in html
