"""
The enforcement side of RBAC: a decorator applied per-view, parallel to
Django's own @login_required, that gates access using the exact same
has_page_permission() resolution the template tag uses for showing/
hiding buttons — so what the UI offers and what the server actually
allows can never silently diverge.
"""
from functools import wraps
from django.shortcuts import redirect, render
from django.contrib import messages

from .rbac import has_page_permission


def page_permission_required(page_key, action='view'):
    """Usage:
        @page_permission_required('user_management', action='view')
        def user_list(request): ...

        @page_permission_required('user_management', action='delete')
        def user_delete(request, user_id): ...

    Requires login first (redirects to the login page, matching
    @login_required's own behavior, rather than showing an access-denied
    page to a logged-out visitor). An authenticated user who is denied
    the specific page/action sees a proper 403 page instead — a genuine
    authorization failure, not just a login prompt."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('accounts:login')
            if not has_page_permission(request.user, page_key, action):
                return render(request, 'accounts/access_denied.html', {
                    'page_key': page_key, 'action': action,
                }, status=403)
            return view_func(request, *args, **kwargs)
        return wrapped_view
    return decorator
