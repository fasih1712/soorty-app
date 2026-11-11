from django.http import Http404

from .access import is_finance_admin, is_finance_path
from . import audit


class FinanceAccessMiddleware:
    """First lock. Blocks EVERYTHING under /finance for anyone but the Super
    Admin before URL routing runs, so a new finance URL added later is
    protected even if its view forgets the decorator.

    Placement in settings.MIDDLEWARE: after AuthenticationMiddleware."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if is_finance_path(request.path_info) and not is_finance_admin(getattr(request, 'user', None)):
            audit.log_denied(request, 'middleware')
            raise Http404()
        return self.get_response(request)
