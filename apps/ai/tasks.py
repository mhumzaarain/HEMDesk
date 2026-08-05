"""All Procrastinate tasks that touch the LLM live in this app (spec §2)."""

from procrastinate.contrib.django import app


@app.periodic(cron="0 3 * * 1")
@app.task(name="ai.compute_risk_scores", retry=3)
def compute_risk_scores(timestamp=None):
    from django.utils import timezone

    from apps.equipment.models import Equipment, EquipmentStatus

    from .models import RiskScoringConfig
    from .services import assess_equipment

    now = timezone.now()
    config = RiskScoringConfig.get()
    for equipment in Equipment.objects.exclude(status=EquipmentStatus.CONDEMNED):
        assess_equipment(equipment, config, now)


@app.periodic(cron="0 4 1 * *")
@app.task(name="ai.generate_monthly_report_scheduled", retry=3)
def generate_monthly_report_scheduled(timestamp=None):
    """On the 1st, generate last month's report."""
    from datetime import date, timedelta

    first_of_this_month = date.today().replace(day=1)
    previous = (first_of_this_month - timedelta(days=1)).replace(day=1)
    generate_monthly_report.defer(month_iso=f"{previous:%Y-%m}")


@app.task(name="ai.generate_monthly_report", retry=3)
def generate_monthly_report(month_iso, requested_by_id=None):
    from datetime import datetime

    from django.core.files.base import ContentFile
    from django.utils import timezone

    from apps.reports import metrics, pdf
    from apps.reports.models import MonthlyReport, ReportStatus

    from . import client, prompts

    month = datetime.strptime(month_iso, "%Y-%m").date()
    report, _ = MonthlyReport.objects.get_or_create(month=month)
    report.status = ReportStatus.GENERATING
    if requested_by_id is not None:
        report.requested_by_id = requested_by_id
    report.save(update_fields=["status", "requested_by"])
    try:
        report.metrics = metrics.month_metrics(month)
        try:
            report.narrative = client.chat(
                prompts.report_narrative_prompt(report.metrics)
            )
        except client.LLMUnavailable:
            report.narrative = None
        if report.pdf:
            report.pdf.delete(save=False)
        report.pdf.save(
            f"monthly-{month_iso}.pdf",
            ContentFile(pdf.render_monthly_pdf(report)),
            save=False,
        )
        report.status = ReportStatus.READY
        report.generated_at = timezone.now()
        report.save()
    except Exception:
        report.status = ReportStatus.FAILED
        report.save(update_fields=["status"])
        raise


@app.task(name="ai.process_manual", retry=2)
def process_manual(manual_id):
    from . import manuals
    from .models import ManualStatus, ServiceManual

    manual = ServiceManual.objects.get(pk=manual_id)
    try:
        manuals.process(manual)
    except Exception:
        manual.status = ManualStatus.FAILED
        manual.status_note = "processing error"
        manual.save(update_fields=["status", "status_note"])
        raise


@app.task(name="ai.answer_assistant_chat", retry=0)
def answer_assistant_chat(message_id, fault_category=None):
    from . import assistant

    assistant.answer(message_id, fault_category=fault_category)
