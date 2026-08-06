import pytest
from django.contrib.auth import authenticate, get_user_model
from django.core.management import call_command
from django.urls import reverse

pytestmark = pytest.mark.django_db


# --- create_superuser management command (env-driven bootstrap) ---


def test_create_superuser_from_env(monkeypatch):
    monkeypatch.setenv("SUPERUSER_USERNAME", "root")
    monkeypatch.setenv("SUPERUSER_EMAIL", "root@example.com")
    monkeypatch.setenv("SUPERUSER_PASSWORD", "s3cret-pw")
    monkeypatch.setenv("SUPERUSER_EMPLOYEE_ID", "ADMIN-0001")
    call_command("create_superuser")
    user = get_user_model().objects.get(username="root")
    assert user.is_superuser and user.is_staff
    assert user.role == "admin"
    assert user.employee_id == "ADMIN-0001"
    assert user.check_password("s3cret-pw")


def test_create_superuser_skips_without_password(monkeypatch):
    monkeypatch.setenv("SUPERUSER_USERNAME", "root")
    monkeypatch.delenv("SUPERUSER_PASSWORD", raising=False)
    call_command("create_superuser")
    assert not get_user_model().objects.filter(username="root").exists()


def test_create_superuser_skips_if_a_superuser_already_exists(monkeypatch):
    get_user_model().objects.create_superuser(
        username="existing",
        email="",
        password="pw",
        employee_id="ADMIN-9999",
        role="admin",
    )
    monkeypatch.setenv("SUPERUSER_USERNAME", "root2")
    monkeypatch.setenv("SUPERUSER_PASSWORD", "pw2")
    monkeypatch.setenv("SUPERUSER_EMPLOYEE_ID", "ADMIN-0002")
    call_command("create_superuser")
    assert not get_user_model().objects.filter(username="root2").exists()


def test_create_superuser_force_resets_password(monkeypatch):
    get_user_model().objects.create_superuser(
        username="root",
        email="",
        password="old-pw",
        employee_id="ADMIN-0001",
        role="admin",
    )
    monkeypatch.setenv("SUPERUSER_USERNAME", "root")
    monkeypatch.setenv("SUPERUSER_PASSWORD", "new-pw-value")
    monkeypatch.setenv("SUPERUSER_EMPLOYEE_ID", "ADMIN-0001")
    call_command("create_superuser", "--force")
    user = get_user_model().objects.get(username="root")
    assert user.check_password("new-pw-value")


# --- self-service change-password page ---


def test_change_password_requires_login(client):
    response = client.get(reverse("password_change"))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


def test_change_password_page_renders(client, staff_user):
    client.force_login(staff_user)
    response = client.get(reverse("password_change"))
    assert response.status_code == 200
    assert b"old_password" in response.content


def test_user_can_change_own_password(client, staff_user):
    client.force_login(staff_user)
    response = client.post(
        reverse("password_change"),
        {
            "old_password": "pw",
            "new_password1": "Brand-New-Pw-123",
            "new_password2": "Brand-New-Pw-123",
        },
    )
    assert response.status_code == 302
    assert response.url == reverse("password_change_done")
    staff_user.refresh_from_db()
    assert staff_user.check_password("Brand-New-Pw-123")
    assert authenticate(username="nurse", password="Brand-New-Pw-123") is not None


def test_change_password_rejects_wrong_old_password(client, staff_user):
    client.force_login(staff_user)
    response = client.post(
        reverse("password_change"),
        {
            "old_password": "wrong-old",
            "new_password1": "Brand-New-Pw-123",
            "new_password2": "Brand-New-Pw-123",
        },
    )
    assert response.status_code == 200  # re-renders with errors
    staff_user.refresh_from_db()
    assert staff_user.check_password("pw")  # unchanged


# --- admin site hides groups and permissions ---


def test_user_admin_form_offers_no_groups_or_permissions(client, django_user_model):
    boss = django_user_model.objects.create_superuser(
        username="root", password="pw", employee_id="EMP-999"
    )
    client.force_login(boss)
    html = client.get(f"/admin/accounts/user/{boss.pk}/change/").content.decode()

    assert 'name="groups"' not in html
    assert 'name="user_permissions"' not in html


def test_admin_index_has_no_groups_section(client, django_user_model):
    boss = django_user_model.objects.create_superuser(
        username="root2", password="pw", employee_id="EMP-998"
    )
    client.force_login(boss)
    html = client.get("/admin/").content.decode()

    assert "/admin/auth/group/" not in html
