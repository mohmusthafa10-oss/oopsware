import secrets
import string

from .models import Role, User

_ALPHABET = "".join(c for c in string.ascii_letters + string.digits if c not in "0O1lI")


def generate_temporary_password(length: int = 14) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def create_user_account(
    *, email: str, full_name: str, role: str = Role.USER, temporary_password: str | None = None
) -> tuple[User, str]:
    """Create an account with a temporary password the user must change at first login.

    Returns (user, plaintext_temporary_password). The plaintext is shown once to the
    admin and never stored.
    """
    password = temporary_password or generate_temporary_password()
    user = User(email=email, full_name=full_name, role=role, must_change_password=True)
    user.set_password(password)
    user.full_clean()
    user.save()
    return user, password


def deactivate_user(user: User) -> None:
    """Deactivate (never delete) an account. Raises ValidationError for the last admin.

    Existing sessions stop working immediately: Django's ModelBackend rejects inactive users.
    """
    user.is_active = False
    user.full_clean()
    user.save(update_fields=["is_active"])