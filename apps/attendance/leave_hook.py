from datetime import date


def approved_leave_dates(user_ids: list[int], start: date, end: date) -> dict[int, set[date]]:
    """Phase 5 Integration Point:

    Returns a mapping of user_id -> set of approved leave dates within [start, end].
    Currently returns an empty set for each user until the leave_requests app is built in Phase 5.
    """
    return {uid: set() for uid in user_ids}
