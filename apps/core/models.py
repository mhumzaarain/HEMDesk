from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import models


class ProtectedQuerySet(models.QuerySet):
    """Bulk delete disabled. Bulk update() stays available (used by seed_demo
    to backdate auto_now_add timestamps)."""

    def delete(self):
        raise TypeError(f"Bulk delete is disabled for {self.model.__name__}")


class NoDeleteModel(models.Model):
    objects = ProtectedQuerySet.as_manager()

    class Meta:
        abstract = True

    def delete(self, *args, **kwargs):
        raise TypeError(f"{self.__class__.__name__} can never be deleted")


class AppendOnlyModel(NoDeleteModel):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise TypeError(f"{self.__class__.__name__} is append-only")
        super().save(*args, **kwargs)


class AuditLog(AppendOnlyModel):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.PROTECT,
        related_name="audit_entries",
    )
    verb = models.CharField(max_length=100)
    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.CharField(max_length=64)
    changes = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.actor} {self.verb}"
