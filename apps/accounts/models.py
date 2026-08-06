from django.contrib.auth.models import AbstractUser
from django.db import models


class Roles(models.TextChoices):
    STAFF = "staff", "Staff"
    ENGINEER = "engineer", "Biomedical Engineer"
    ADMIN = "admin", "Admin"


class User(AbstractUser):
    employee_id = models.CharField(max_length=30, unique=True)
    role = models.CharField(max_length=20, choices=Roles.choices, default=Roles.STAFF)
    department = models.ForeignKey(
        "equipment.Department",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="users",
    )

    REQUIRED_FIELDS = ["employee_id"]

    is_staff = models.BooleanField(
        "Can open the admin site (administrators only)",
        default=False,
        help_text="Set automatically from the Role field. Role Admin grants "
        "access; Staff and Biomedical Engineer do not.",
    )

    def save(self, *args, **kwargs):
        # is_staff is Django's switch for admin-site access, and HEMDesk
        # grants it from the Role field alone — nobody setting up an account
        # should have to know the two are connected. Superusers keep access
        # whatever their role: createsuperuser does not prompt for one, and
        # stripping it would lock the only administrator out.
        self.is_staff = self.is_superuser or self.role == Roles.ADMIN
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = set(kwargs["update_fields"]) | {"is_staff"}
        super().save(*args, **kwargs)

    @property
    def is_engineer_or_admin(self) -> bool:
        return self.role in (Roles.ENGINEER, Roles.ADMIN)

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.employee_id})"
