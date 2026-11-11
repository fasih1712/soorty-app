"""
The single definition of "who may use Finance".

Decision D1: only the Django Super Admin (an active user with
is_superuser=True). Roles, groups, Django permissions and the per-user
page-permission overrides play NO part here, and Finance pages are
deliberately NOT registered in apps/accounts/rbac.py, so they can never
appear in the Role Management matrix.

Every guard in this app (middleware, view decorator, data layer) calls
is_finance_admin() so the rule lives in exactly one place.
"""

FINANCE_URL_PREFIX = '/finance'


def is_finance_admin(user):
    return bool(
        getattr(user, 'is_authenticated', False)
        and getattr(user, 'is_active', False)
        and getattr(user, 'is_superuser', False)
    )


def is_finance_path(path):
    """True for /finance, /finance/..., in any letter case, even with extra
    leading slashes. Deliberately broader than Django's own URL matching:
    over-matching only returns a 404, under-matching would skip the guard."""
    normalised = '/' + (path or '').lstrip('/')
    normalised = normalised.lower()
    return normalised == FINANCE_URL_PREFIX or normalised.startswith(FINANCE_URL_PREFIX + '/')
