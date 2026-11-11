def sidebar_summary(request):
    """Injects sidebar_listed / sidebar_sold into every template's context, so the
    sidebar's 'Quick Summary' widget (in base.html, present on every page) always
    shows real numbers rather than being wired up per-view. Reuses the already
    cached fetch_home_summary() — no extra DB load per page."""
    if not getattr(request, 'user', None) or not request.user.is_authenticated:
        return {}
    try:
        from apps.wastage.oracle_data import fetch_home_summary
        summary = fetch_home_summary()
        return {
            'sidebar_listed': summary.get('listed', 0),
            'sidebar_sold': summary.get('sold', 0),
        }
    except Exception:
        # Never let a sidebar widget break the whole page if the DB/cache hiccups
        return {'sidebar_listed': 0, 'sidebar_sold': 0}
