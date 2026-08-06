from django.db import migrations
from django.db.models import Q


def align_is_staff(apps, schema_editor):
    """Bring existing rows into line with the rule 0003 only declared.

    0003 altered the field but changed no data, so until each user is next
    saved -- which happens lazily, on their next login -- is_staff keeps
    whatever it was. A legacy engineer with is_staff=True would keep admin-site
    access, and the admin changelist would show stale values for everyone.
    """
    User = apps.get_model("accounts", "User")
    grants = Q(is_superuser=True) | Q(role="admin")
    User.objects.filter(grants).exclude(is_staff=True).update(is_staff=True)
    User.objects.exclude(grants).exclude(is_staff=False).update(is_staff=False)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_alter_user_is_staff"),
    ]

    operations = [
        # Irreversible on purpose: the values this overwrites are not recorded
        # anywhere, so there is nothing to restore. Reversing is a no-op rather
        # than an error because the state left behind is the correct one --
        # every earlier migration can still be unapplied over the top of it.
        migrations.RunPython(align_is_staff, migrations.RunPython.noop),
    ]
