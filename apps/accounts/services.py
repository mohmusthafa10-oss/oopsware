import secrets
import string

from apps.audit import services as audit_services
from .models import Role, User

_ALPHABET = "".join(c for c in string.ascii_letters + string.digits if c not in "0O1lI")


def generate_temporary_password(length: int = 14) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def create_user_account(
    *,
    email: str,
    full_name: str,
    role: str = Role.USER,
    temporary_password: str | None = None,
    actor=None,
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

    audit_services.record(
        actor=actor,
        action=audit_services.USER_CREATED,
        target=user,
        before=None,
        after={
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
            "is_active": user.is_active,
        },
    )
    return user, password


def deactivate_user(user: User, actor=None) -> None:
    """Deactivate (never delete) an account. Raises ValidationError for the last admin.

    Existing sessions stop working immediately: Django's ModelBackend rejects inactive users.
    """
    before_state = {"is_active": user.is_active, "deactivated_at": user.deactivated_at}
    user.is_active = False
    user.full_clean()
    user.save(update_fields=["is_active"])

    audit_services.record(
        actor=actor,
        action=audit_services.USER_DEACTIVATED,
        target=user,
        before=before_state,
        after={"is_active": user.is_active, "deactivated_at": user.deactivated_at},
    )


def reactivate_user(user: User, actor=None) -> None:
    """Reactivate a previously deactivated account."""
    before_state = {"is_active": user.is_active, "deactivated_at": user.deactivated_at}
    user.is_active = True
    user.full_clean()
    user.save(update_fields=["is_active"])

    audit_services.record(
        actor=actor,
        action=audit_services.USER_REACTIVATED,
        target=user,
        before=before_state,
        after={"is_active": user.is_active, "deactivated_at": user.deactivated_at},
    )