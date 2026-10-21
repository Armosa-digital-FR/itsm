"""Navigation principale : n'affiche que les sections dont la route existe."""

from django.urls import NoReverseMatch, reverse

NAV = [
    ("Tickets", "helpdesk:ticket_list", "helpdesk", {"ticket_list", "ticket_detail", "ticket_new"}),
    ("Suivi", "helpdesk:tracking", "helpdesk", {"tracking"}),
    ("Base de résolution", "helpdesk:knowledge", "helpdesk", {"knowledge"}),
    (
        "Parc",
        "inventory:equipment_list",
        "inventory",
        {"equipment_list", "equipment_detail", "equipment_new"},
    ),
    (
        "Licences",
        "inventory:licence_list",
        "inventory",
        {"licence_list", "licence_detail", "licence_new"},
    ),
]


def navigation(request):
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated and getattr(user, "is_technician", False)):
        return {"nav_items": []}
    match = getattr(request, "resolver_match", None)
    items = []
    for label, name, namespace, url_names in NAV:
        try:
            url = reverse(name)
        except NoReverseMatch:
            continue
        active = bool(match and match.namespace == namespace and match.url_name in url_names)
        items.append({"label": label, "url": url, "active": active})
    if user.is_admin:
        items.append({"label": "Administration", "url": reverse("admin:index"), "active": False})
    return {"nav_items": items}
