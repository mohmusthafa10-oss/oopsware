import pytest

from apps.accounts.models import Role, User

PASSWORD = "Str0ng-Pass-9xQ!"


@pytest.fixture
def password():
    return PASSWORD


@pytest.fixture
def admin_account(db):
    return User.objects.create_user(
        email="boss@example.com", password=PASSWORD, full_name="Asha Admin", role=Role.ADMIN
    )


@pytest.fixture
def member(db):
    return User.objects.create_user(
        email="team@example.com", password=PASSWORD, full_name="Ravi Member", role=Role.USER
    )