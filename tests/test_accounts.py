import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_user_has_employee_id_and_role(staff_user):
    assert staff_user.employee_id == "EMP-001"
    assert staff_user.role == "staff"
    assert staff_user.is_engineer_or_admin is False


def test_engineer_and_admin_helper(engineer, admin_user):
    assert engineer.is_engineer_or_admin is True
    assert admin_user.is_engineer_or_admin is True


def test_employee_id_unique(staff_user):
    with pytest.raises(Exception):
        get_user_model().objects.create_user(
            username="other", password="pw", employee_id="EMP-001"
        )


def test_login_page_renders(client):
    response = client.get("/accounts/login/")
    assert response.status_code == 200


def test_home_requires_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


def test_login_page_shows_logo(client):
    # the logo renders via the base-template nav and the login card
    response = client.get("/accounts/login/")
    assert b"img/logo.png" in response.content


def test_admin_link_shown_to_staff_users(client, django_user_model):
    superadmin = django_user_model.objects.create_user(
        username="root",
        password="pw",
        employee_id="EMP-999",
        role="admin",
        is_staff=True,
        is_superuser=True,
    )
    client.force_login(superadmin)
    response = client.get(reverse("equipment_list"))
    assert b'href="/admin/"' in response.content


def test_admin_link_hidden_from_non_staff(client, engineer):
    client.force_login(engineer)
    response = client.get(reverse("equipment_list"))
    assert b'href="/admin/"' not in response.content


def test_admin_role_grants_admin_site_access(db, django_user_model):
    user = django_user_model.objects.create_user(
        username="chief", password="pw", employee_id="EMP-500", role="admin"
    )
    assert user.is_staff is True


def test_engineer_and_staff_roles_do_not_grant_admin_site_access(db, django_user_model):
    for username, role in [("eng9", "engineer"), ("nurse9", "staff")]:
        user = django_user_model.objects.create_user(
            username=username, password="pw", employee_id=f"EMP-{username}", role=role
        )
        assert user.is_staff is False


def test_changing_the_role_flips_admin_site_access(db, django_user_model):
    user = django_user_model.objects.create_user(
        username="promoted", password="pw", employee_id="EMP-501", role="staff"
    )
    assert user.is_staff is False

    user.role = "admin"
    user.save()
    user.refresh_from_db()
    assert user.is_staff is True

    user.role = "engineer"
    user.save()
    user.refresh_from_db()
    assert user.is_staff is False


def test_changing_only_the_role_still_writes_is_staff(db, django_user_model):
    user = django_user_model.objects.create_user(
        username="partial", password="pw", employee_id="EMP-504", role="staff"
    )
    user.role = "admin"
    user.save(update_fields=["role"])
    user.refresh_from_db()
    assert user.is_staff is True


def test_ticking_is_staff_by_hand_does_not_survive_a_save(db, django_user_model):
    user = django_user_model.objects.create_user(
        username="sneaky", password="pw", employee_id="EMP-502", role="staff"
    )
    user.is_staff = True
    user.save()
    user.refresh_from_db()
    assert user.is_staff is False


def test_a_superuser_keeps_admin_site_access_whatever_the_role(db, django_user_model):
    # createsuperuser does not prompt for a role, so a superuser can end up
    # with the default Staff role. Stripping is_staff here would lock the only
    # administrator out of the admin site.
    boss = django_user_model.objects.create_superuser(
        username="root3", password="pw", employee_id="EMP-503"
    )
    assert boss.role == "staff"
    assert boss.is_staff is True

    boss.save()
    boss.refresh_from_db()
    assert boss.is_staff is True


def test_align_is_staff_migration_backfills_rows_that_disagree(db, django_user_model):
    """0003 is an AlterField only: on an existing database is_staff keeps its
    old value until the row is next saved. 0004 backfills it."""
    import importlib

    from django.apps import apps as global_apps

    migration = importlib.import_module("apps.accounts.migrations.0004_align_is_staff")

    def make(username, employee_id, role, stale_is_staff, superuser=False):
        maker = (
            django_user_model.objects.create_superuser
            if superuser
            else django_user_model.objects.create_user
        )
        user = maker(
            username=username, password="pw", employee_id=employee_id, role=role
        )
        # .update() bypasses User.save(), which is exactly how a legacy row
        # gets to disagree with its role in the first place.
        django_user_model.objects.filter(pk=user.pk).update(is_staff=stale_is_staff)
        return user

    legacy_engineer = make("legacy-eng", "EMP-L1", "engineer", True)
    stale_admin = make("legacy-admin", "EMP-L2", "admin", False)
    stale_boss = make("legacy-root", "EMP-L3", "staff", False, superuser=True)
    plain_staff = make("legacy-nurse", "EMP-L4", "staff", False)

    migration.align_is_staff(global_apps, None)

    def is_staff(user):
        return django_user_model.objects.get(pk=user.pk).is_staff

    assert is_staff(legacy_engineer) is False
    assert is_staff(stale_admin) is True
    assert is_staff(stale_boss) is True
    assert is_staff(plain_staff) is False


def test_saving_with_an_empty_update_fields_writes_nothing(db, django_user_model):
    """Django treats update_fields=[] as "save nothing" and returns early;
    the is_staff override must not turn that into an UPDATE."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    user = django_user_model.objects.create_user(
        username="noop", password="pw", employee_id="EMP-505", role="staff"
    )
    user.role = "admin"

    with CaptureQueriesContext(connection) as ctx:
        user.save(update_fields=[])

    assert ctx.captured_queries == []
    user.refresh_from_db()
    assert user.role == "staff"
    assert user.is_staff is False
