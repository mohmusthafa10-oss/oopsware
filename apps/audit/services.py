from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from django.contrib.contenttypes.models import ContentType

from .models import AuditLog

# Action constants
USER_CREATED = "USER_CREATED"
USER_DEACTIVATED = "USER_DEACTIVATED"
USER_REACTIVATED = "USER_REACTIVATED"
SCHEDULE_CREATED = "SCHEDULE_CREATED"
HOLIDAY_CREATED = "HOLIDAY_CREATED"
HOLIDAY_UPDATED = "HOLIDAY_UPDATED"
HOLIDAY_DELETED = "HOLIDAY_DELETED"
CALENDAR_POLICY_CREATED = "CALENDAR_POLICY_CREATED"
CORRECTION_APPROVED = "CORRECTION_APPROVED"
CORRECTION_REJECTED = "CORRECTION_REJECTED"


def _sanitize_for_json(val):
    if val is None:
        return None
    if isinstance(val, (datetime, date, time)):
        return val.isoformat()
    if isinstance(val, (Decimal, UUID)):
        return str(val)
    if isinstance(val, dict):
        return {str(k): _sanitize_for_json(v) for k, v in val.items()}
    if isinstance(val, (list, tuple, set)):
        return [_sanitize_for_json(v) for v in val]
    return val


def record(actor, action: str, target, before=None, after=None) -> AuditLog:
    """Record an immutable append-only audit log entry."""
    target_ct = None
    target_id = None
    target_str = str(target) if target is not None else ""

    if target is not None and hasattr(target, "pk"):
        target_ct = ContentType.objects.get_for_model(target)
        target_id = str(target.pk)

    return AuditLog.objects.create(
        actor=actor if actor and getattr(actor, "is_authenticated", False) else None,
        action=action,
        target_content_type=target_ct,
        target_object_id=target_id,
        target_repr=target_str[:255],
        before=_sanitize_for_json(before),
        after=_sanitize_for_json(after),
    )
