from django.conf import settings as django_settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from pgvector.django import HnswIndex, VectorField

from apps.core.models import AppendOnlyModel
from apps.equipment.models import Equipment

RISK_WINDOW_MONTHS = 12  # fixed design constant — deliberately not in config


class RiskScoringConfig(models.Model):
    """Singleton. Exactly two admin-editable numbers (spec §4)."""

    points_per_repair = models.PositiveIntegerField(default=1)
    high_risk_threshold = models.PositiveIntegerField(default=3)

    class Meta:
        verbose_name = "risk scoring configuration"

    @classmethod
    def get(cls) -> "RiskScoringConfig":
        config, _ = cls.objects.get_or_create(pk=1)
        return config

    def __str__(self):
        return (
            f"{self.points_per_repair} point(s)/repair, "
            f"high-risk at {self.high_risk_threshold}"
        )


class RiskAssessment(AppendOnlyModel):
    equipment = models.ForeignKey(
        Equipment, on_delete=models.PROTECT, related_name="risk_assessments"
    )
    score = models.IntegerField()
    factors = models.JSONField(default=dict)
    narrative = models.TextField(null=True, blank=True)
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-generated_at"]

    def __str__(self):
        return f"{self.equipment} score={self.score} @ {self.generated_at:%Y-%m-%d}"


class ManualStatus(models.TextChoices):
    PROCESSING = "processing", "Processing"
    READY = "ready", "Ready"
    FAILED = "failed", "Failed"


class ServiceManual(models.Model):
    """One manual per (manufacturer, model_number) — covers every unit of
    that model. Deliberately deletable/replaceable: it is reference material,
    not clinical history."""

    manufacturer = models.CharField(max_length=200)
    model_number = models.CharField(max_length=100)
    title = models.CharField(max_length=300)
    file = models.FileField(upload_to="manuals/")
    uploaded_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="manuals_uploaded",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=20, choices=ManualStatus.choices, default=ManualStatus.PROCESSING
    )
    status_note = models.CharField(max_length=300, blank=True)
    page_count = models.PositiveIntegerField(default=0)
    # Which embedding model produced this manual's chunk vectors. Empty =
    # no vectors (or stale after a config change) → retrieval uses FTS only.
    embedding_model = models.CharField(max_length=100, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["manufacturer", "model_number"], name="one_manual_per_model"
            )
        ]

    @classmethod
    def for_equipment(cls, equipment):
        return cls.objects.filter(
            manufacturer__iexact=equipment.manufacturer,
            model_number__iexact=equipment.model_number,
            status=ManualStatus.READY,
        ).first()

    def __str__(self):
        return f"{self.title} ({self.manufacturer} {self.model_number})"


class ManualChunk(models.Model):
    manual = models.ForeignKey(
        ServiceManual, on_delete=models.CASCADE, related_name="chunks"
    )
    text = models.TextField()
    page_start = models.PositiveIntegerField()
    page_end = models.PositiveIntegerField()
    search = SearchVectorField(null=True)
    embedding = VectorField(dimensions=django_settings.EMBEDDING_DIM, null=True)

    class Meta:
        indexes = [
            GinIndex(fields=["search"]),
            HnswIndex(
                name="ai_chunk_embedding_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
        ]


class AssistantRole(models.TextChoices):
    USER = "user", "User"
    ASSISTANT = "assistant", "Assistant"


class AssistantMessage(models.Model):
    """Device-scoped chat history, shared between engineers (spec §6)."""

    equipment = models.ForeignKey(
        Equipment, on_delete=models.PROTECT, related_name="assistant_messages"
    )
    work_order = models.ForeignKey(
        "maintenance.WorkOrder",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="assistant_messages",
    )
    user = models.ForeignKey(
        django_settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assistant_messages",
    )
    role = models.CharField(max_length=10, choices=AssistantRole.choices)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
