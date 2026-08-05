"""Prompt assembly and answering for the engineer assistant (spec §6).
The device is never inferred from text — it always comes in as a model
instance from the page the chat lives on."""

import logging

from apps.maintenance.models import FaultCategory

from . import client, retrieval
from .models import AssistantMessage, AssistantRole, ServiceManual

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are an advisory assistant for hospital biomedical engineers, helping "
    "troubleshoot one specific device. Ground every suggestion in the manual "
    "sections and repair history provided; cite manual page numbers when you "
    "use them. If the provided material does not cover the question, say so "
    "plainly. You cannot perform actions — only advise. Keep answers short "
    "and practical."
)

UNAVAILABLE_TEXT = "The assistant is not available right now — please try again."

HISTORY_TURNS = 10


def _device_card(equipment):
    return (
        f"Device: {equipment.name} — {equipment.manufacturer} "
        f"{equipment.model_number}, serial {equipment.serial_number}, "
        f"department {equipment.department.name}, status {equipment.status}"
    )


def _work_order_block(work_order):
    if work_order is None:
        return "No active work order context."
    complaints = "\n".join(
        f"- complaint: {c.description[:400]}" for c in work_order.complaints.all()
    )
    remarks = "\n".join(
        f"- remark ({r.kind}): {r.text[:400]}" for r in work_order.remarks.all()
    )
    return (
        f"Work order #{work_order.id} ({work_order.status}):\n"
        f"{complaints or '- no complaints attached'}\n"
        f"{remarks or '- no remarks yet'}"
    )


def _manual_block(equipment, question):
    manual = ServiceManual.for_equipment(equipment)
    if manual is None:
        return "No service manual is on file for this model."
    sections = retrieval.manual_sections(manual, question)
    if not sections:
        return f"No sections of '{manual.title}' matched the question."
    return "\n\n".join(
        f"Manual p. {s.page_start}"
        + (f"-{s.page_end}" if s.page_end != s.page_start else "")
        + f": {s.text[:800]}"
        for s in sections
    )


def _similar_repairs_block(equipment, question, fault_category, exclude_wo_id):
    rows = retrieval.similar_repairs(
        equipment,
        question,
        fault_category=fault_category,
        exclude_wo_id=exclude_wo_id,
    )
    if not rows:
        return "No similar past repairs found for this model."
    lines = []
    for row in rows:
        lines.append(
            f"- WO #{row['wo_id']} ({row['fault_category'] or 'uncategorized'}): "
            f"complaints: {'; '.join(row['complaints'])[:300]} | "
            f"resolution remarks: {'; '.join(row['remarks'])[:300]}"
        )
    return "\n".join(lines)


def _history_block(equipment):
    turns = list(
        equipment.assistant_messages.order_by("-created_at")[:HISTORY_TURNS]
    )[::-1]
    return "\n".join(f"{m.role}: {m.content[:300]}" for m in turns) or "none"


def build_messages(equipment, work_order, question, fault_category=None):
    category_label = (
        FaultCategory(fault_category).label if fault_category else "all"
    )
    exclude_wo_id = work_order.id if work_order else None
    repairs = _similar_repairs_block(
        equipment, question, fault_category, exclude_wo_id
    )
    context = (
        f"{_device_card(equipment)}\n\n"
        f"== Work-order context ==\n{_work_order_block(work_order)}\n\n"
        f"== Service manual sections ==\n{_manual_block(equipment, question)}\n\n"
        f"== Similar past repairs (same model, category: {category_label}) ==\n"
        f"{repairs}\n\n"
        f"== Recent chat ==\n{_history_block(equipment)}\n\n"
        f"Engineer's question: {question}"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": context},
    ]


def answer(message_id, fault_category=None) -> AssistantMessage:
    question = AssistantMessage.objects.select_related(
        "equipment__department", "work_order", "user"
    ).get(pk=message_id)
    try:
        messages = build_messages(
            question.equipment,
            question.work_order,
            question.content,
            fault_category=fault_category,
        )
        content = client.chat(messages, interactive=True)
    except client.LLMUnavailable:
        content = UNAVAILABLE_TEXT
    except Exception:
        # The panel polls until a reply row exists, so every failure must
        # still persist a visible answer — never leave the thread hanging.
        logger.exception("assistant answer failed for message %s", message_id)
        content = UNAVAILABLE_TEXT
    return AssistantMessage.objects.create(
        equipment=question.equipment,
        work_order=question.work_order,
        user=question.user,
        role=AssistantRole.ASSISTANT,
        content=content,
    )
