"""Pastille « Mentions » de l'en-tête (FR-014d)."""


def mentions(request):
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated and getattr(user, "is_technician", False)):
        return {}
    from helpdesk.services.mentions import unread_count

    return {"mentions_unread": unread_count(user)}
