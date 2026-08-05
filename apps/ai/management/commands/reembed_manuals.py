"""Re-embed all ready manuals with the configured embedding backend
(spec §5). Run after changing EMBEDDING_MODEL/EMBEDDING_DIM or to backfill
manuals uploaded while the backend was down."""

import sys

from django.core.management.base import BaseCommand

from apps.ai import manuals
from apps.ai.models import ManualStatus, ServiceManual


class Command(BaseCommand):
    help = "Re-embed every ready service manual with the configured EMBEDDING_MODEL."

    def handle(self, *args, **options):
        failed = 0
        queryset = ServiceManual.objects.filter(status=ManualStatus.READY)
        for manual in queryset:
            if manuals.embed_and_stamp(manual):
                self.stdout.write(f"{manual}: ok")
            else:
                failed += 1
                self.stderr.write(f"{manual}: FAILED — kept keyword-only")
            manual.save(update_fields=["embedding_model", "status_note"])
        total = queryset.count()
        self.stdout.write(f"{total - failed}/{total} manuals embedded")
        if failed:
            sys.exit(1)
