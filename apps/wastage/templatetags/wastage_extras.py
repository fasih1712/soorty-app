from django import template

register = template.Library()

# A small, fixed palette — cycles by name so the SAME department always gets
# the SAME color (stable across requests/restarts), without ever hardcoding
# specific department names. Scales to any number of future departments.
_PALETTE = ['slate', 'emerald', 'amber', 'sky', 'purple']


@register.filter(name='badge_color')
def badge_color(value):
    """Returns a palette key (e.g. 'slate', 'emerald') deterministically
    derived from the given string, for use as a CSS class suffix like
    `dept-badge-{{ name|badge_color }}`. Uses a simple stable checksum
    (NOT Python's built-in hash(), which is randomized per-process for
    strings and would give a different color after every restart)."""
    if not value:
        return _PALETTE[0]
    checksum = sum(ord(ch) for ch in str(value))
    return _PALETTE[checksum % len(_PALETTE)]


@register.filter(name='doc_id_from_ref')
def doc_id_from_ref(value):
    """Sales Header/Line ledger entries store SOURCE_REF as 'DOC-2026-0001#20'
    (doc_id # line_no) since SOURCE_ID is NUMBER and doc_id is a string PK.
    This pulls just the doc_id back out for building a drill-down link."""
    if not value:
        return ''
    return str(value).split('#')[0]
