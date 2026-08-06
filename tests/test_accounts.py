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
        username="root", password="pw", employee_id="EMP-999",
        role="admin", is_staff=True, is_superuser=True,
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
