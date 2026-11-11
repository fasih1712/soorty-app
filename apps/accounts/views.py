from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from .models import CustomUser, PageRegistry, UserPagePermissionOverride, PagePermissionAnchor, Division
from .decorators import page_permission_required
from .rbac import has_page_permission


def login_view(request):
    if request.user.is_authenticated:
        return redirect('wastage:home')
    if request.method == 'POST':
        user = authenticate(request, username=request.POST['username'], password=request.POST['password'])
        if user:
            selected_division = request.POST.get('division', '').strip()
            # A privileged (sees_all_divisions) account isn't tied to one division,
            # so it isn't subject to this check — everyone else must select the
            # exact division their account is assigned to.
            if not getattr(user, 'sees_all_divisions', False) and selected_division != user.division:
                messages.error(request, '❌ This account is not authorized for the selected division.')
                return render(request, 'accounts/login.html', {
                    'form': request.POST, 'division_choices': CustomUser.DIVISION_CHOICES,
                })
            login(request, user)
            return redirect('wastage:home')
        else:
            messages.error(request, 'Invalid username or password.')
    return render(request, 'accounts/login.html', {
        'form': request.POST if request.method == 'POST' else None,
        'division_choices': CustomUser.DIVISION_CHOICES,
    })


def logout_view(request):
    if request.method == 'POST':
        logout(request)
    return redirect('accounts:login')


# ═══════════════════════════════════════════════════════════════════
# RBAC helpers shared by the User and Role views below
# ═══════════════════════════════════════════════════════════════════

def _matrix_pages():
    """Every active registered page, in display order — the row set for
    both the Role and User permission matrices."""
    return PageRegistry.objects.filter(is_active=True).order_by('module_group', 'display_order', 'label')


def _rbac_permission_qs():
    """Every Django Permission this app's own RBAC system created (attached
    to the PagePermissionAnchor content type) — deliberately scoped so
    Role-matrix saves only ever touch OUR page permissions, never any
    other Permission a Group might separately hold (e.g. Django admin's
    own built-in ones)."""
    content_type = ContentType.objects.get_for_model(PagePermissionAnchor)
    return Permission.objects.filter(content_type=content_type)


def _apply_role_matrix_post(group, post_data):
    """Reconciles a Group's page permissions to exactly match the checked
    boxes in the submitted matrix -- adds what's newly checked, removes
    what's newly unchecked, leaves everything else (any non-RBAC
    permission the group might hold) untouched."""
    rbac_permissions = {p.codename: p for p in _rbac_permission_qs()}
    current = set(group.permissions.filter(id__in=[p.id for p in rbac_permissions.values()]).values_list('codename', flat=True))
    desired = set()
    for page in _matrix_pages():
        for action in page.ACTIONS:
            if not page.action_applies(action):
                continue
            field = f'perm_{page.key}_{action}'
            if post_data.get(field):
                desired.add(page.codename(action))

    to_add = [rbac_permissions[c] for c in (desired - current) if c in rbac_permissions]
    to_remove = [rbac_permissions[c] for c in (current - desired) if c in rbac_permissions]
    if to_add:
        group.permissions.add(*to_add)
    if to_remove:
        group.permissions.remove(*to_remove)


def _apply_user_override_matrix_post(user, post_data, granted_by):
    """Reconciles a user's UserPagePermissionOverride rows to match the
    submitted 3-state matrix (inherit / grant / deny) exactly -- creates
    or updates an override for anything set to grant/deny, and deletes
    any existing override for anything explicitly set back to inherit."""
    for page in _matrix_pages():
        for action in page.ACTIONS:
            if not page.action_applies(action):
                continue
            field = f'override_{page.key}_{action}'
            value = post_data.get(field, 'inherit')
            existing = UserPagePermissionOverride.objects.filter(user=user, page=page, action=action).first()
            if value == 'inherit':
                if existing:
                    existing.delete()
            else:
                grant = (value == 'grant')
                if existing:
                    if existing.grant != grant:
                        existing.grant = grant
                        existing.granted_by = granted_by
                        existing.save()
                else:
                    UserPagePermissionOverride.objects.create(
                        user=user, page=page, action=action, grant=grant, granted_by=granted_by,
                    )


def _matrix_context_for_user(user):
    """Builds the per-cell state the User permission matrix template
    needs: for every (page, action), whether the user's role(s) grant it
    by default, and whether an explicit override exists on top of that.

    Handles the brand-new-user case explicitly: a CustomUser() that
    hasn't been saved yet (the Add User form's initial GET) has no pk,
    so it can't be used in a related-object filter at all -- Django
    raises ValueError for that, not just an empty queryset. An unsaved
    user can't have any overrides anyway (there's no row for anything
    to point at yet), so short-circuiting to an empty dict here is
    exactly correct, not just a crash-avoidance shortcut."""
    overrides = {}
    if user.pk:
        overrides = {
            (o.page_id, o.action): o.grant
            for o in UserPagePermissionOverride.objects.filter(user=user).select_related('page')
        }
    rows = []
    for page in _matrix_pages():
        cells = []
        for action in page.ACTIONS:
            role_default = user.has_perm(f'accounts.{page.codename(action)}') if user.pk else False
            override_value = overrides.get((page.id, action))
            cells.append({
                'action': action,
                'role_default': role_default,
                'override': override_value,  # None = inherit, True = grant, False = deny
                'applicable': page.action_applies(action),
            })
        rows.append({'page': page, 'cells': cells})
    return rows


def _matrix_context_for_role(group):
    """Builds the per-cell checked state the Role permission matrix
    template needs: for every (page, action), whether this group
    currently grants it."""
    granted = set()
    if group and group.pk:
        granted = set(
            group.permissions.filter(id__in=[p.id for p in _rbac_permission_qs()]).values_list('codename', flat=True)
        )
    rows = []
    for page in _matrix_pages():
        cells = []
        for action in page.ACTIONS:
            cells.append({
                'action': action,
                'checked': page.codename(action) in granted,
                'applicable': page.action_applies(action),
            })
        rows.append({'page': page, 'cells': cells})
    return rows


# ═══════════════════════════════════════════════════════════════════
# User Management — Phase 1: locked down first, per sign-off
# ═══════════════════════════════════════════════════════════════════

@page_permission_required('user_management', action='view')
def user_list(request):
    users = CustomUser.objects.all().order_by('username').prefetch_related('groups')
    return render(request, 'accounts/user_list.html', {'users': users})


def _lookup_datatex_user(datatex_user_id):
    """Looks up one ID_ in ACT_ID_USER_VW and returns its FIRST_ (display
    name), or None if that ID doesn't exist there at all. Shared by the
    Add User form's server-side validation (never trust a client-
    submitted name for a value that should come from the authoritative
    source) and the live auto-populate lookup endpoint below."""
    from apps.wastage.oracle_data import get_connection

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT FIRST_ FROM ACT_ID_USER_VW WHERE ID_ = :1",
                [datatex_user_id],
            )
            row = cur.fetchone()
    if not row:
        return None
    return (row[0] or '').strip()


@page_permission_required('user_management', action='view')
def datatex_lookup(request):
    """GET ?datatex_id=NASIB01 -> {"found": true, "first_name": "..."} or
    {"found": false}. Powers the live auto-populate on the Add User form
    as an admin types a Datatex ID -- gated behind the same 'view'
    permission as the rest of User Management, not left open, since it
    lets an authenticated user probe which IDs exist."""
    from django.http import JsonResponse

    datatex_id = request.GET.get('datatex_id', '').strip()
    if not datatex_id:
        return JsonResponse({'found': False})

    name = _lookup_datatex_user(datatex_id)
    if name is None:
        return JsonResponse({'found': False})
    return JsonResponse({'found': True, 'first_name': name})


def _search_datatex_users(query, limit=20):
    """Fuzzy match against ACT_ID_USER_VW by name OR id, for the
    autocomplete dropdown. Deliberately separate from
    _lookup_datatex_user() above, which stays an exact-match lookup --
    that one is also relied on for server-side validation at submit
    time (never trust a client-submitted name/id pairing for what
    should come from the authoritative source), so it's left
    untouched rather than repurposed. Results capped at `limit` so a
    single-character query against a large centralized view can't
    return an unusably long list -- ordered by name so a capped result
    is still a sensible, predictable slice rather than arbitrary
    database order."""
    from apps.wastage.oracle_data import get_connection

    like_query = f'%{query}%'
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT ID_, FIRST_ FROM ACT_ID_USER_VW
                   WHERE UPPER(FIRST_) LIKE UPPER(:1) OR UPPER(ID_) LIKE UPPER(:2)
                   ORDER BY FIRST_
                   FETCH FIRST :3 ROWS ONLY""",
                [like_query, like_query, limit],
            )
            rows = cur.fetchall()
    return [{'id': r[0], 'name': (r[1] or '').strip()} for r in rows]


@page_permission_required('user_management', action='view')
def datatex_search(request):
    """GET ?q=taha -> {"results": [{"id": "10402", "name": "Syed Taha
    Javaid"}, ...]}. Powers the searchable autocomplete on the Datatex
    User ID field (Add User and Edit User) -- fuzzy matches by name or
    id as the admin types, same 'view' permission gate as
    datatex_lookup() above and the same reasoning for it (this also
    lets an authenticated user enumerate centralized-system users, so
    it isn't left open). Empty or single-character queries return no
    results rather than querying the view with an overly broad LIKE --
    avoids a near-unfiltered fetch on every keystroke before the admin
    has actually typed enough to narrow anything down."""
    from django.http import JsonResponse

    query = request.GET.get('q', '').strip()
    if len(query) < 2:
        return JsonResponse({'results': []})

    results = _search_datatex_users(query)
    return JsonResponse({'results': results})


@page_permission_required('user_management', action='create')
def user_create(request):
    if request.method == 'POST':
        datatex_user_id = request.POST.get('datatex_user_id', '').strip()
        role       = request.POST.get('role')
        department = request.POST.get('department')
        employee_id = request.POST.get('employee_id')
        division   = request.POST.get('division') or CustomUser._meta.get_field('division').default
        sees_all_divisions = request.POST.get('sees_all_divisions') == 'on'

        if not datatex_user_id:
            messages.error(request, '❌ Datatex User ID is required.')
        elif CustomUser.objects.filter(username=datatex_user_id).exists():
            messages.error(request, f'A user mapped to "{datatex_user_id}" already exists.')
        else:
            # Authoritative name comes from the same lookup that powers
            # the live auto-populate -- never trust a client-submitted
            # name for this. Also doubles as validating the ID is real
            # right now, rather than failing silently at first login.
            display_name = _lookup_datatex_user(datatex_user_id)
            if display_name is None:
                messages.error(request, f'❌ "{datatex_user_id}" was not found in the centralized system. Check the ID and try again.')
            else:
                try:
                    # username == datatex_user_id by design -- every user
                    # created through this form is Datatex-mapped, per
                    # the confirmed requirement. password=None makes
                    # Django call set_unusable_password() itself: there
                    # is no local password for this account, ever --
                    # CustomDatatexAuthBackend is the only way in.
                    user = CustomUser.objects.create_user(
                        username=datatex_user_id,
                        first_name=display_name,
                        password=None,
                    )
                    user.role = role
                    user.department = department
                    user.employee_id = employee_id if employee_id else None
                    user.division = division
                    user.sees_all_divisions = sees_all_divisions
                    user.datatex_user_id = datatex_user_id
                    user.save()

                    group_ids = request.POST.getlist('groups')
                    if group_ids:
                        user.groups.set(Group.objects.filter(id__in=group_ids))
                    division_codes = request.POST.getlist('divisions')
                    if division_codes:
                        user.divisions.set(Division.objects.filter(code__in=division_codes))
                    _apply_user_override_matrix_post(user, request.POST, granted_by=request.user)

                    messages.success(request, f'✅ User "{display_name}" ({datatex_user_id}) created successfully!')
                    return redirect('accounts:user_list')
                except Exception as e:
                    messages.error(request, f'❌ Error: {str(e)}')

    return render(request, 'accounts/user_create.html', {
        'division_choices': CustomUser.DIVISION_CHOICES,
        'all_groups': Group.objects.all().order_by('name'),
        'selected_group_ids': [],
        'matrix_rows': _matrix_context_for_user(CustomUser()),
    })


@page_permission_required('user_management', action='edit')
def user_edit(request, user_id):
    user = get_object_or_404(CustomUser, id=user_id)

    if request.method == 'POST':
        user.email      = request.POST.get('email')
        user.first_name = request.POST.get('first_name')
        user.last_name  = request.POST.get('last_name')
        user.role       = request.POST.get('role')
        user.department = request.POST.get('department')
        user.employee_id = request.POST.get('employee_id') or None
        user.is_active  = request.POST.get('is_active') == 'on'
        user.division   = request.POST.get('division') or user.division
        user.sees_all_divisions = request.POST.get('sees_all_divisions') == 'on'
        user.datatex_user_id = request.POST.get('datatex_user_id', '').strip() or None

        # Security invariant, enforced here regardless of what the form
        # submitted: a Datatex-mapped account (whether it already was
        # one, or just became one in this same edit) can NEVER end up
        # with a working local password. Without this, typing anything
        # into the password field for a mapped user would silently
        # re-open the exact dual-password hole this whole change exists
        # to close -- Django's own set_password() doesn't know or care
        # that this account is supposed to be centrally-authenticated.
        new_password = request.POST.get('password')
        if user.datatex_user_id:
            user.set_unusable_password()
        elif new_password:
            user.set_password(new_password)

        try:
            user.save()
            group_ids = request.POST.getlist('groups')
            user.groups.set(Group.objects.filter(id__in=group_ids))
            division_codes = request.POST.getlist('divisions')
            user.divisions.set(Division.objects.filter(code__in=division_codes))
            _apply_user_override_matrix_post(user, request.POST, granted_by=request.user)

            messages.success(request, f'✅ User "{user.username}" updated successfully!')
            return redirect('accounts:user_list')
        except Exception as e:
            messages.error(request, f'❌ Error: {str(e)}')

    return render(request, 'accounts/user_edit.html', {
        'edit_user': user,
        'division_choices': CustomUser.DIVISION_CHOICES,
        'all_groups': Group.objects.all().order_by('name'),
        'selected_group_ids': list(user.groups.values_list('id', flat=True)),
        'selected_division_codes': list(user.divisions.values_list('code', flat=True)),
        'matrix_rows': _matrix_context_for_user(user),
    })


@page_permission_required('user_management', action='delete')
def user_delete(request, user_id):
    user = get_object_or_404(CustomUser, id=user_id)
    if request.method == 'POST':
        if user == request.user:
            messages.error(request, "❌ You can't delete your own account.")
        else:
            username = user.username
            user.delete()
            messages.success(request, f'✅ User "{username}" deleted successfully!')
    return redirect('accounts:user_list')


# ═══════════════════════════════════════════════════════════════════
# Role Management — new in this phase. Sets default permissions for a
# Group; individual users can still be given overrides on top of it via
# the User Management screens above.
# ═══════════════════════════════════════════════════════════════════

@page_permission_required('role_management', action='view')
def role_list(request):
    groups = Group.objects.all().order_by('name').prefetch_related('user_set')
    return render(request, 'accounts/role_list.html', {'groups': groups})


@page_permission_required('role_management', action='create')
def role_create(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, '❌ Role name is required.')
        elif Group.objects.filter(name=name).exists():
            messages.error(request, f'❌ A role named "{name}" already exists.')
        else:
            group = Group.objects.create(name=name)
            _apply_role_matrix_post(group, request.POST)
            messages.success(request, f'✅ Role "{name}" created successfully!')
            return redirect('accounts:role_list')

    return render(request, 'accounts/role_form.html', {
        'group': None,
        'matrix_rows': _matrix_context_for_role(None),
    })


@page_permission_required('role_management', action='edit')
def role_edit(request, group_id):
    group = get_object_or_404(Group, id=group_id)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, '❌ Role name is required.')
        elif Group.objects.filter(name=name).exclude(id=group.id).exists():
            messages.error(request, f'❌ A role named "{name}" already exists.')
        else:
            group.name = name
            group.save()
            _apply_role_matrix_post(group, request.POST)
            messages.success(request, f'✅ Role "{name}" updated successfully!')
            return redirect('accounts:role_list')

    return render(request, 'accounts/role_form.html', {
        'group': group,
        'matrix_rows': _matrix_context_for_role(group),
    })


@page_permission_required('role_management', action='delete')
def role_delete(request, group_id):
    group = get_object_or_404(Group, id=group_id)
    if request.method == 'POST':
        member_count = group.user_set.count()
        if member_count:
            messages.error(request, f'❌ Cannot delete "{group.name}" — {member_count} user(s) still assigned to it. Reassign them first.')
        else:
            name = group.name
            group.delete()
            messages.success(request, f'✅ Role "{name}" deleted successfully!')
    return redirect('accounts:role_list')
