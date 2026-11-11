"""
Custom authentication backend integrating the centralized Datatex
ACT_ID_USER_VW view.

Design: whether a login attempt is checked centrally or locally is
driven entirely by whether the matched local account HAS a
datatex_user_id mapping set -- not by is_superuser or any hardcoded
username list (per the approved design decision). This means:
  - The two existing local accounts, and any future local-only account,
    stay on standard Django password auth automatically, simply by
    never being mapped through User Management -- no special-casing
    needed, and nothing breaks if a username is later renamed.
  - Any account explicitly mapped via User Management authenticates
    against ACT_ID_USER_VW (ID_ + PWD_, plaintext match) instead.

On a successful centralized login, this also syncs the account's
first_name from ACT_ID_USER_VW.FIRST_ and saves it -- the rest of the
app already displays first_name / get_full_name() everywhere (sidebar,
user list, __str__), so writing it here is the one place needed, and it
stays in sync on every login, not just the first one.

Subclasses ModelBackend purely to inherit get_user() (and
user_can_authenticate()) for free -- authenticate() is fully overridden
below, the parent's version is never called.
"""
from django.contrib.auth.backends import ModelBackend
from .models import CustomUser


class CustomDatatexAuthBackend(ModelBackend):

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None

        try:
            user = CustomUser.objects.get(username=username)
        except CustomUser.DoesNotExist:
            return None

        if not self.user_can_authenticate(user):
            return None

        if user.datatex_user_id:
            return self._authenticate_centralized(user, password)

        # Local-only account (no mapping) -- standard Django password
        # check, same behavior as the built-in ModelBackend.
        return user if user.check_password(password) else None

    def _authenticate_centralized(self, user, password):
        # NOTE: ACT_ID_USER_VW is queried unqualified here, matching how
        # you described the connection ("same instance, existing
        # apxWastage connection"). If apxWastage can't resolve it
        # unqualified, this will fail with the same ORA-00942 pattern
        # we hit repeatedly during the wst_djn_* migration -- same fix
        # either way: a private synonym in apxWastage's schema, or tell
        # me which schema owns the view and I'll qualify this directly.
        from apps.wastage.oracle_data import get_connection

        with get_connection(username=user.username) as conn:
            with conn.cursor() as cur:
                # Parameterized even though the comparison itself is a
                # plaintext match, as specified -- this protects against
                # SQL injection regardless of how PWD_ is stored; it's
                # not related to hashing.
                cur.execute(
                    "SELECT FIRST_ FROM ACT_ID_USER_VW WHERE ID_ = :1 AND PWD_ = :2",
                    [user.datatex_user_id, password],
                )
                row = cur.fetchone()

        if not row:
            return None

        display_name = (row[0] or '').strip()
        if display_name and user.first_name != display_name:
            user.first_name = display_name
            user.save(update_fields=['first_name'])

        return user
