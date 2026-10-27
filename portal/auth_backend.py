from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class PortalBackend(ModelBackend):
    """Same login as Django's, but the user, employee profile and designation come back in ONE query.

    The portal needs all three on every page (sidebar, permissions), and every database round trip
    to a hosted PostgreSQL costs time, so this saves two queries per click.
    """

    def get_user(self, user_id):
        User = get_user_model()
        try:
            user = User._default_manager.select_related(
                "employee__designation", "employee__department", "employee__team"
            ).get(pk=user_id)
        except (User.DoesNotExist, ValueError, TypeError):
            return None
        return user if self.user_can_authenticate(user) else None
