import pytest
from django.urls import reverse

from apps.accounts import services

pytestmark = pytest.mark.django_db

NEW_PASSWORD = "An0ther-Str0ng-One!"


def test_login_is_case_insensitive_and_routes_by_role(client, member, password):
    resp = client.post(reverse("login"), {"username": "TEAM@Example.com", "password": password})
    assert resp.status_code == 302
    assert client.get(reverse("home")).url == reverse("user_dashboard")


def test_admin_lands_on_admin_dashboard(client, admin_account, password):
    client.post(reverse("login"), {"username": admin_account.email, "password": password})
    assert client.get(reverse("home")).url == reverse("manage_dashboard")


def test_wrong_password_rejected(client, member):
    resp = client.post(reverse("login"), {"username": member.email, "password": "nope"})
    assert resp.status_code == 200
    assert "_auth_user_id" not in client.session


def test_inactive_user_cannot_log_in(client, member, password):
    member.is_active = False
    member.save()
    client.post(reverse("login"), {"username": member.email, "password": password})
    assert "_auth_user_id" not in client.session


def test_deactivation_kills_existing_session(client, member):
    client.force_login(member)
    assert client.get(reverse("user_dashboard")).status_code == 200
    member.is_active = False
    member.save()
    resp = client.get(reverse("user_dashboard"))
    assert resp.status_code == 302 and reverse("login") in resp.url


def test_logout_requires_post(client, member):
    client.force_login(member)
    assert client.get(reverse("logout")).status_code == 405
    assert client.post(reverse("logout")).status_code == 302
    assert "_auth_user_id" not in client.session


def test_forced_password_change_flow(client):
    user, temp = services.create_user_account(email="new@example.com", full_name="New Hire")
    client.force_login(user)

    resp = client.get(reverse("user_dashboard"))
    assert resp.status_code == 302 and resp.url == reverse("password_change")
    assert client.get(reverse("password_change")).status_code == 200

    resp = client.post(
        reverse("password_change"),
        {"old_password": temp, "new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD},
    )
    assert resp.status_code == 302
    user.refresh_from_db()
    assert not user.must_change_password
    assert user.check_password(NEW_PASSWORD)
    assert client.get(reverse("user_dashboard")).status_code == 200


def test_new_password_must_differ_from_temporary(client):
    user, temp = services.create_user_account(email="new@example.com", full_name="New Hire")
    client.force_login(user)
    resp = client.post(
        reverse("password_change"),
        {"old_password": temp, "new_password1": temp, "new_password2": temp},
    )
    assert resp.status_code == 200
    user.refresh_from_db()
    assert user.must_change_password