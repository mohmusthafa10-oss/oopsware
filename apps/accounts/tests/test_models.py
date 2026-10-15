import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.accounts import services
from apps.accounts.models import Role, User

pytestmark = pytest.mark.django_db


def test_create_user_lowercases_email_and_hashes_password(password):
    user = User.objects.create_user(email="Mixed@Example.COM", password=password, full_name="M")
    assert user.email == "mixed@example.com"
    assert user.password != password
    assert user.check_password(password)
    assert user.role == Role.USER


def test_email_unique_case_insensitively(password):
    User.objects.create_user(email="a@example.com", password=password, full_name="A")
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create_user(email="A@example.com", password=password, full_name="A2")


def test_superuser_is_admin_and_can_use_django_admin(password):
    user = User.objects.create_superuser(email="root@example.com", password=password, full_name="R")
    assert user.is_admin and user.is_staff and user.is_superuser


def test_product_admin_cannot_use_django_admin(admin_account):
    assert admin_account.is_admin
    assert not admin_account.is_staff


def test_only_users_track_attendance(admin_account, member):
    assert member.tracks_attendance
    assert not admin_account.tracks_attendance


def test_cannot_deactivate_last_admin(admin_account):
    with pytest.raises(ValidationError):
        services.deactivate_user(admin_account)
    admin_account.refresh_from_db()
    assert admin_account.is_active


def test_cannot_demote_last_admin(admin_account):
    admin_account.role = Role.USER
    with pytest.raises(ValidationError):
        admin_account.full_clean()


def test_can_deactivate_admin_when_another_exists(admin_account, password):
    User.objects.create_user(
        email="second@example.com", password=password, full_name="Second", role=Role.ADMIN
    )
    services.deactivate_user(admin_account)
    admin_account.refresh_from_db()
    assert not admin_account.is_active


def test_create_user_account_forces_password_change():
    user, temp = services.create_user_account(email="New@Example.com", full_name="New Hire")
    assert user.must_change_password
    assert user.email == "new@example.com"
    assert user.check_password(temp)
    assert len(temp) >= 12