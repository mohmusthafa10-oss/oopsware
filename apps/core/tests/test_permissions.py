import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db

PROTECTED = ["home", "manage_dashboard", "user_dashboard"]


@pytest.mark.parametrize("name", PROTECTED)
def test_anonymous_redirected_to_login(client, name):
    resp = client.get(reverse(name))
    assert resp.status_code == 302
    assert resp.url.startswith(reverse("login"))


def test_member_cannot_open_admin_area(client, member):
    client.force_login(member)
    assert client.get(reverse("manage_dashboard")).status_code == 403
    assert client.get(reverse("user_dashboard")).status_code == 200


def test_admin_has_no_member_dashboard(client, admin_account):
    client.force_login(admin_account)
    assert client.get(reverse("manage_dashboard")).status_code == 200
    assert client.get(reverse("user_dashboard")).status_code == 403


def test_navigation_differs_by_role(client, member, admin_account):
    client.force_login(member)
    assert b"My Dashboard" in client.get(reverse("user_dashboard")).content
    client.force_login(admin_account)
    html = client.get(reverse("manage_dashboard")).content
    assert b"My Dashboard" not in html and b"Dashboard" in html