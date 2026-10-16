from django.urls import reverse

ADMIN_NAV = [
    {"label": "Dashboard", "url_name": "manage_dashboard"},
    {"label": "Members", "url_name": "manage_members"},
    {"label": "Attendance", "url_name": "manage_attendance"},
    {"label": "Holiday Calendar", "url_name": "manage_calendar"},
]

MEMBER_NAV = [
    {"label": "My Dashboard", "url_name": "user_dashboard"},
    {"label": "My Attendance", "url_name": "user_attendance"},
]


def navigation(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    items = ADMIN_NAV if user.is_admin else MEMBER_NAV
    current = request.resolver_match.url_name if request.resolver_match else None
    return {
        "nav_items": [
            {
                "label": item["label"],
                "url": reverse(item["url_name"]),
                "active": current == item["url_name"],
            }
            for item in items
        ]
    }