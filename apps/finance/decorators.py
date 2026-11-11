from functools import wraps

from django.http import Http404

from .access import is_finance_admin
from . import audit


def super_admin_required(view_func):
    """Second lock behind FinanceAccessMiddleware. Anyone who is not the
    Super Admin (including a logged-out visitor) gets a plain 404, so the
    module's existence is not revealed. Every finance view must carry it;
    the test suite fails if one does not."""
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not is_finance_admin(getattr(request, 'user', None)):
            audit.log_denied(request, 'view-guard')
            raise Http404()
        return view_func(request, *args, **kwargs)
    wrapped._finance_guarded = True
    return wrapped
