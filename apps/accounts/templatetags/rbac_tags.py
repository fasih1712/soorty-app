"""
{% load rbac_tags %}
{% has_permission 'sales_orders' 'create' as can_create %}
{% if can_create %}<a href="...">New Sale Document</a>{% endif %}

Deliberately calls the exact same has_page_permission() function the
@page_permission_required decorator uses — a button that's shown here
and a request that's allowed by the decorator are always answering the
identical question, so the UI can never offer an action the server
would then refuse.
"""
from django import template
from apps.accounts.rbac import has_page_permission

register = template.Library()


@register.simple_tag(takes_context=True)
def has_permission(context, page_key, action='view'):
    request = context.get('request')
    if request is None:
        return False
    return has_page_permission(request.user, page_key, action)
