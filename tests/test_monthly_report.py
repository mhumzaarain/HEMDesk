from datetime import date

import pytest
from django.utils import timezone

from apps.maintenance.models import WorkOrderStatus
from apps.reports import metrics
from apps.reports.models import MonthlyReport


def test_month_metrics_is_json_serializable(db, make_work_order, fault):
    import json

    now = timezone.now()
    make_work_order(
        status=WorkOrderStatus.COMPLETED,
        repair_completed_at=now,
        fault_category=fault("electrical"),
    )
    month = date(now.year, now.month, 1)
    data = metrics.month_metrics(month)
    json.dumps(data)  # must not raise
    assert data["repairs_completed"] == 1
    assert data["month"] == f"{now:%Y-%m}"


def test_monthly_report_unique_per_month(db):
    MonthlyReport.objects.create(month=date(2026, 6, 1))
    with pytest.raises(Exception):
        MonthlyReport.objects.create(month=date(2026, 6, 1))
