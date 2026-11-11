import json
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.http import JsonResponse, HttpResponse
from apps.accounts.decorators import page_permission_required
from apps.accounts.rbac import has_page_permission
from .oracle_data import *

# Single source of truth for valid divisions across the whole app.
# To add a new division (e.g. '11', '16', '19'): add it to
# CustomUser.DIVISION_CHOICES in apps/accounts/models.py + a migration.
# Every dropdown, filter, and validation check below reads from here —
# nothing else needs to change.
_DIVISION_CHOICES = get_user_model().DIVISION_CHOICES
_VALID_DIVISIONS = {code for code, _label in _DIVISION_CHOICES}


@login_required
def wastage_home(request):
    sees_all = getattr(request.user, 'sees_all_divisions', False)
    division = None if sees_all else getattr(request.user, 'division', '08')
    return render(request, 'wastage/home.html', {
        'summary': fetch_home_summary(),
        'dash': fetch_home_dashboard(division),
    })


@login_required
@page_permission_required('categories', action='view')
def category_list(request):
    search = request.GET.get('q', '').strip()
    data = fetch_all_categories(search=search if search else None)
    return render(request, 'wastage/category_list.html', {'records': data, 'search': search})


@login_required
@page_permission_required('categories', action='create')
def category_add(request):
    if request.method == 'POST':
        # Grid se dynamic array fields pull kiye
        names = request.POST.getlist('category_name[]')
        descriptions = request.POST.getlist('description[]')
        prefixes = request.POST.getlist('prefix[]')

        rows = []
        seen = set()
        seen_prefixes = set()
        has_error = False

        for i in range(len(names)):
            name = names[i].strip()
            if not name:
                continue  # Empty sheets rows skipped seamlessly

            key = name.lower()
            if key in seen:
                messages.error(request, f'❌ Duplicate category name "{name}" in this batch.')
                has_error = True
                continue
            
            if check_duplicate('wst_djn_categories', 'CATEGORY_NAME', name):
                messages.error(request, f'❌ Category "{name}" already exists. Please use a different name.')
                has_error = True
                continue

            prefix = prefixes[i].strip().upper() if i < len(prefixes) else ''
            if prefix:
                if prefix in seen_prefixes:
                    messages.error(request, f'❌ Duplicate prefix "{prefix}" in this batch.')
                    has_error = True
                    continue
                if check_duplicate('wst_djn_categories', 'PREFIX', prefix):
                    messages.error(request, f'❌ Prefix "{prefix}" is already used by another category.')
                    has_error = True
                    continue
                seen_prefixes.add(prefix)

            seen.add(key)
            rows.append({
                'name': name,
                'desc': descriptions[i].strip() if i < len(descriptions) else '',
                'prefix': prefix,
            })

        if not rows:
            if not has_error:
                messages.error(request, '❌ Please add at least one category row.')
        elif has_error:
            messages.error(request, '❌ Fix the errors above before saving. No categories were saved.')
        else:
            try:
                for row in rows:
                    # Aapka exact original function insert call
                    insert_category(row['name'], row['desc'], prefix=row['prefix'], username=request.user.username)
                    log_audit('CATEGORIES', row['name'], 'CREATE', request.user.username)
                
                messages.success(request, f'✅ {len(rows)} category(ies) added successfully!')
                return redirect('wastage:category_list')
            except Exception as e:
                messages.error(request, f'❌ Error: {e}')

    # Naye excel Look grid k liye category_form template redirect 
    existing_categories = fetch_all_categories()
    return render(request, 'wastage/category_form.html', {
        'title': 'Add Category', 
        'record': None,
        'existing_names': [c['CATEGORY_NAME'] for c in existing_categories if c.get('CATEGORY_NAME')],
    })


@login_required
@page_permission_required('categories', action='edit')
def category_edit(request, cat_id):
    record = fetch_category_by_id(cat_id)
    if not record:
        return redirect('wastage:category_list')
        
    if request.method == 'POST':
        name = request.POST.get('category_name', '').strip()
        desc = request.POST.get('description', '').strip()
        prefix = request.POST.get('prefix', '').strip().upper()
        
        if not name:
            messages.error(request, '❌ Category name is required.')
        elif check_duplicate('wst_djn_categories', 'CATEGORY_NAME', name, exclude_value=cat_id, exclude_pk_col='CATEGORY_ID'):
            messages.error(request, f'❌ Category "{name}" already exists. Please use a different name.')
        elif prefix and check_duplicate('wst_djn_categories', 'PREFIX', prefix, exclude_value=cat_id, exclude_pk_col='CATEGORY_ID'):
            messages.error(request, f'❌ Prefix "{prefix}" is already used by another category.')
        else:
            try:
                old_data = {'CATEGORY_NAME': record['CATEGORY_NAME'], 'DESCRIPTION': record['DESCRIPTION'], 'PREFIX': record.get('PREFIX')}
                new_data = {'CATEGORY_NAME': name, 'DESCRIPTION': desc, 'PREFIX': prefix}
                
                update_category(cat_id, name, desc, prefix=prefix, username=request.user.username)
                log_audit('CATEGORIES', cat_id, 'UPDATE', request.user.username, old_data, new_data)
                
                messages.success(request, '✅ Category updated!')
                return redirect('wastage:category_list')
            except Exception as e:
                messages.error(request, f'❌ Error: {e}')

    return render(request, 'wastage/category_form.html', {
        'title': f'Edit Category — {record["CATEGORY_NAME"]}', 
        'record': record
    })


@login_required
@page_permission_required('categories', action='delete')
def category_delete(request, cat_id):
    if request.method == 'POST':
        try:
            record = fetch_category_by_id(cat_id)
            delete_category(cat_id, username=request.user.username)
            log_audit('CATEGORIES', cat_id, 'DELETE', request.user.username, record)
            messages.success(request, '✅ Category deleted!')
        except Exception as e:
            messages.error(request, f'❌ Error: {e}')
    return redirect('wastage:category_list')

@login_required
@page_permission_required('departments', action='view')
def department_list(request):
    search = request.GET.get('q', '').strip()
    return render(request, 'wastage/department_list.html', {
        'records': fetch_all_departments(search=search if search else None),
        'search': search
    })


# ─── DEPARTMENTS ──────────────────────────────────────────
@login_required
@page_permission_required('departments', action='create')
def department_add(request):
    if request.method == 'POST':
        names = request.POST.getlist('dept_name[]')
        locations = request.POST.getlist('location[]')
        supervisor_ids = request.POST.getlist('supervisor_id[]')
        short_descs = request.POST.getlist('short_description[]')

        rows = []
        seen = set()
        has_error = False

        for i in range(len(names)):
            name = names[i].strip()
            if not name:
                continue

            key = name.lower()
            if key in seen:
                messages.error(request, f'❌ Duplicate department name "{name}" in this batch.')
                has_error = True
                continue

            if check_duplicate('wst_djn_departments', 'DEPT_NAME', name):
                messages.error(request, f'❌ Department "{name}" already exists.')
                has_error = True
                continue

            seen.add(key)
            rows.append({
                'name': name,
                'short_description': short_descs[i].strip() if i < len(short_descs) else '',
                'location': locations[i].strip() if i < len(locations) else '',
                'supervisor_id': supervisor_ids[i].strip() if i < len(supervisor_ids) else None
            })

        if not rows:
            if not has_error:
                messages.error(request, '❌ Please add at least one department row.')
        elif has_error:
            messages.error(request, '❌ Fix the errors above before saving. No departments were saved.')
        else:
            try:
                for row in rows:
                    insert_department(
                        row['name'], 
                        row['location'], 
                        row['supervisor_id'], 
                        username=request.user.username,
                        short_description=row['short_description']
                    )
                    log_audit('DEPARTMENTS', row['name'], 'CREATE', request.user.username)			

                messages.success(request, f'✅ {len(rows)} department(s) added successfully!')
                return redirect('wastage:department_list')
            except Exception as e:
                messages.error(request, f'❌ Error: {e}')

    existing_departments = fetch_all_departments()
    return render(request, 'wastage/department_form.html', {
        'title': 'Add Department', 
        'record': None,
        'existing_names': [d['DEPT_NAME'] for d in existing_departments if d.get('DEPT_NAME')],
    })
	

@login_required
@page_permission_required('departments', action='edit')
def department_edit(request, dept_id):
    # 🌟 SAFELY CLEANED: Explicitly department ka function call karein
    record = fetch_department_by_id(dept_id)
    
    if not record:
        messages.error(request, '❌ Department not found.')
        return redirect('wastage:department_list')

    if request.method == 'POST':
        name = request.POST.get('dept_name', '').strip()
        location = request.POST.get('location', '').strip()
        supervisor_id = request.POST.get('supervisor_id', '').strip()
        short_description = request.POST.get('short_description', '').strip()

        if not name:
            messages.error(request, '❌ Department name is required.')
        elif check_duplicate('wst_djn_departments', 'DEPT_NAME', name, exclude_value=dept_id, exclude_pk_col='DEPT_ID'):
            messages.error(request, f'❌ Department "{name}" already exists.')
        else:
            try:
                old_data = {'DEPT_NAME': record.get('DEPT_NAME'), 'SHORT_DESCRIPTION': record.get('SHORT_DESCRIPTION'), 'LOCATION': record.get('LOCATION')}
                new_data = {'DEPT_NAME': name, 'SHORT_DESCRIPTION': short_description or None, 'LOCATION': location}
                
                update_department(dept_id, name, location, supervisor_id, username=request.user.username,
                                  short_description=short_description)
                log_audit('DEPARTMENTS', dept_id, 'UPDATE', request.user.username, old_data, new_data)
                
                messages.success(request, '✅ Department updated!')
                return redirect('wastage:department_list')
            except Exception as e:
                messages.error(request, f'❌ Error: {e}')

    return render(request, 'wastage/department_form.html', {
        'title': 'Edit Department', 
        'record': record
    })

@login_required
@page_permission_required('departments', action='delete')
def department_delete(request, dept_id):
    if request.method == 'POST':
        try:
            record = fetch_department_by_id(dept_id)
            # 🌟 FIXED: Delete mein bhi username pass karein taake session database level par validate ho
            delete_department(dept_id, username=request.user.username)
            log_audit('DEPARTMENTS', dept_id, 'DELETE', request.user.username, record)
            messages.success(request, '✅ Department deleted!')
        except Exception as e:
            messages.error(request, f'❌ Error: {e}')
    return redirect('wastage:department_list')


# ─── VENDORS ──────────────────────────────────────────────
CNIC_ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.pdf'}
CNIC_ALLOWED_CONTENT_TYPES = {'image/jpeg', 'image/png', 'application/pdf'}
CNIC_MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB -- reasonable default for a scanned ID document; adjust if needed


CNIC_ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.pdf'}
CNIC_ALLOWED_CONTENT_TYPES = {'image/jpeg', 'image/png', 'application/pdf'}
CNIC_MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB -- reasonable default for a scanned ID document; adjust if needed


def _validate_cnic_file(uploaded_file):
    """Raises ValueError with a user-facing message if this upload isn't
    an allowed CNIC file type/size. Deliberately doesn't save anything --
    separated from saving so a bulk-add batch can validate every row's
    file BEFORE committing any of them, matching how every other per-row
    validation in that form already works (validate the whole batch
    first, save nothing if any row fails)."""
    import os
    ext = os.path.splitext(uploaded_file.name)[1].lower()
    if ext not in CNIC_ALLOWED_EXTENSIONS:
        raise ValueError(f'"{uploaded_file.name}": only JPEG, PNG, or PDF files are allowed for CNIC.')
    if uploaded_file.content_type not in CNIC_ALLOWED_CONTENT_TYPES:
        raise ValueError(f'"{uploaded_file.name}": file content does not match a JPEG, PNG, or PDF.')
    if uploaded_file.size > CNIC_MAX_FILE_SIZE:
        raise ValueError(f'"{uploaded_file.name}" is too large (max 5MB).')


def _save_cnic_file(uploaded_file, vendor_id):
    """Saves an already-validated CNIC file under MEDIA_ROOT and returns
    the saved path -- the exact value to store in CNIC_ATTACHMENT_PATH.
    default_storage.save() handles filename-collision-avoidance safely
    on its own, no manual path juggling needed."""
    import os
    from django.core.files.storage import default_storage
    ext = os.path.splitext(uploaded_file.name)[1].lower()
    return default_storage.save(f'vendor_cnic/{vendor_id}{ext}', uploaded_file)


@login_required
@page_permission_required('vendors', action='view')
def vendor_cnic_view(request, vendor_id):
    """Serves a vendor's CNIC attachment for inline preview. Gated by
    'vendors' view permission specifically -- regardless of which module
    the link was clicked from (Vendor Master or Quotation), viewing a
    vendor's CNIC document requires vendor-level access. A user who can
    see Quotations but not Vendors should not be able to see this just
    because a quotation happens to link to it."""
    from django.core.files.storage import default_storage
    from django.http import FileResponse, Http404
    import mimetypes

    record = fetch_vendor_by_id(vendor_id)
    file_path = record.get('CNIC_ATTACHMENT_PATH') if record else None
    if not file_path or not default_storage.exists(file_path):
        raise Http404('No CNIC attachment on file for this vendor.')

    content_type, _ = mimetypes.guess_type(file_path)
    return FileResponse(
        default_storage.open(file_path, 'rb'),
        content_type=content_type or 'application/octet-stream',
        as_attachment=False,  # preview inline, don't force a download prompt
    )


# ─── VENDORS ──────────────────────────────────────────────
@login_required
@page_permission_required('vendors', action='view')
def vendor_list(request):
    search = request.GET.get('q', '').strip()
    return render(request, 'wastage/vendor_list.html', {
        'records': fetch_all_vendors(search=search if search else None),
        'search': search
    })


@login_required
@page_permission_required('vendors', action='create')
def vendor_add(request):
    if request.method == 'POST':
        import re
        # Row indices are discovered directly from the submitted field
        # names (vendor_name_<idx>) rather than tracked via a separate
        # count field. Each row's idx is assigned once when the row is
        # added and never reused even after a different row is removed
        # -- using it as the single key for BOTH text fields and the
        # optional file means a row with no CNIC attachment can never
        # be confused with a different row's file, unlike a plain
        # positional list (request.FILES.getlist(...)) would risk:
        # file inputs left empty are omitted from request.FILES
        # entirely, so positional lists silently go out of alignment
        # the moment any row in the middle has no file.
        row_indices = sorted(set(
            int(m.group(1)) for key in request.POST
            for m in [re.match(r'^vendor_name_(\d+)$', key)] if m
        ))

        rows = []
        seen = set()
        has_error = False

        for idx in row_indices:
            name = request.POST.get(f'vendor_name_{idx}', '').strip()
            if not name:
                continue  # skip fully blank rows defensively
            key = name.lower()
            if key in seen:
                messages.error(request, f'❌ Duplicate vendor name "{name}" in this batch.')
                has_error = True
                continue
            if check_duplicate('wst_djn_vendors', 'VENDOR_NAME', name):
                messages.error(request, f'❌ Vendor "{name}" already exists.')
                has_error = True
                continue
            cnic_val = request.POST.get(f'cnic_{idx}', '').strip()
            if not cnic_val:
                messages.error(request, f'❌ CNIC is required for vendor "{name}".')
                has_error = True
                continue

            # CNIC attachment is optional at creation time (unlike the
            # CNIC number itself, which is required) -- validated now so
            # a bad file blocks the whole batch like any other row error,
            # but only actually saved to disk after insert, once each row
            # has a real VENDOR_ID to name its file after.
            cnic_file = request.FILES.get(f'cnic_attachment_{idx}')
            if cnic_file:
                try:
                    _validate_cnic_file(cnic_file)
                except ValueError as e:
                    messages.error(request, f'❌ {e}')
                    has_error = True
                    continue

            seen.add(key)
            rows.append({
                'name': name,
		'cnic': cnic_val,
                'cnic_file': cnic_file,
                'contact_person': request.POST.get(f'contact_person_{idx}', ''),
                'phone': request.POST.get(f'phone_{idx}', ''),
                'whatsapp_no': request.POST.get(f'whatsapp_no_{idx}', ''),
                'email': request.POST.get(f'email_{idx}', ''),
                'address': request.POST.get(f'address_{idx}', ''),
                'is_active': request.POST.get(f'is_active_{idx}') == 'on',
            })

        if not rows:
            if not has_error:
                messages.error(request, '❌ Please add at least one vendor.')
        elif has_error:
            messages.error(request, '❌ Fix the errors above before saving. No vendors were saved.')
        else:
            try:
                for row in rows:
                    new_vendor_id = insert_vendor(
                        row['name'], row['cnic'], row['contact_person'], row['phone'],
                        row['whatsapp_no'], row['email'], row['address'],
                        row['is_active'], username=request.user.username
                    )
                    if row['cnic_file']:
                        saved_path = _save_cnic_file(row['cnic_file'], new_vendor_id)
                        update_vendor(
                            new_vendor_id, row['name'], row['cnic'], row['contact_person'],
                            row['phone'], row['whatsapp_no'], row['email'], row['address'],
                            row['is_active'], cnic_attachment_path=saved_path, username=request.user.username
                        )
                    log_audit('VENDORS', row['name'], 'CREATE', request.user.username)
                messages.success(request, f'✅ {len(rows)} vendor(s) added!')
                return redirect('wastage:vendor_list')
            except Exception as e:
                messages.error(request, f'❌ Error: {e}')

    existing_vendors = fetch_all_vendors()
    return render(request, 'wastage/vendor_form.html', {
        'title': 'Add Party', 'record': None,
        'existing_names': [v['VENDOR_NAME'] for v in existing_vendors if v.get('VENDOR_NAME')],
    })

@login_required
@page_permission_required('vendors', action='edit')
def vendor_edit(request, vendor_id):
    record = fetch_vendor_by_id(vendor_id)
    if not record:
        return redirect('wastage:vendor_list')
    if request.method == 'POST':
        name = request.POST.get('vendor_name', '').strip()
        cnic = request.POST.get('cnic', '').strip()
        if check_duplicate('wst_djn_vendors', 'VENDOR_NAME', name, exclude_value=vendor_id, exclude_pk_col='VENDOR_ID'):
            messages.error(request, f'❌ Vendor "{name}" already exists.')
        elif not cnic:
            messages.error(request, '❌ CNIC is required.')
        else:
            # Default to the existing attachment path -- only replaced
            # below if a new file was actually uploaded this edit. This
            # is what keeps a re-save that doesn't touch the CNIC upload
            # field from silently wiping out the existing attachment.
            cnic_attachment_path = record.get('CNIC_ATTACHMENT_PATH')
            new_cnic_file = request.FILES.get('cnic_attachment')
            upload_error = None
            if new_cnic_file:
                try:
                    _validate_cnic_file(new_cnic_file)
                except ValueError as e:
                    upload_error = str(e)

            if upload_error:
                messages.error(request, f'❌ {upload_error}')
            else:
                try:
                    if new_cnic_file:
                        from django.core.files.storage import default_storage
                        old_path = record.get('CNIC_ATTACHMENT_PATH')
                        cnic_attachment_path = _save_cnic_file(new_cnic_file, vendor_id)
                        if old_path and default_storage.exists(old_path):
                            default_storage.delete(old_path)

                    old_data = {'VENDOR_NAME': record['VENDOR_NAME'], 'PHONE': record['PHONE']}
                    new_data = {'VENDOR_NAME': name, 'PHONE': request.POST.get('phone', '')}
                    update_vendor(
                        vendor_id, name, cnic, request.POST.get('contact_person', ''),
                        request.POST.get('phone', ''), request.POST.get('whatsapp_no', ''),
                        request.POST.get('email', ''), request.POST.get('address', ''),
                        request.POST.get('is_active') == 'on',
                        cnic_attachment_path=cnic_attachment_path, username=request.user.username
                    )
                    log_audit('VENDORS', vendor_id, 'UPDATE', request.user.username, old_data, new_data)
                    messages.success(request, '✅ Vendor updated!')
                    return redirect('wastage:vendor_list')
                except Exception as e:
                    messages.error(request, f'❌ Error: {e}')
    return render(request, 'wastage/vendor_form.html', {'title': 'Edit Party', 'record': record})

@login_required
@page_permission_required('vendors', action='delete')
def vendor_delete(request, vendor_id):
    if request.method == 'POST':
        try:
            record = fetch_vendor_by_id(vendor_id)
            delete_vendor(vendor_id, username=request.user.username)
            log_audit('VENDORS', vendor_id, 'DELETE', request.user.username, record)
            messages.success(request, '✅ Vendor deleted!')
        except Exception as e:
            messages.error(request, f'❌ Error: {e}')
    return redirect('wastage:vendor_list')


# ─── ITEMS ────────────────────────────────────────────────
@login_required
@page_permission_required('items', action='view')
def item_list(request):
    search = request.GET.get('q', '').strip()
    return render(request, 'wastage/item_list.html', {
        'records': fetch_all_items(search=search if search else None),
        'search': search
    })


@login_required
@page_permission_required('items', action='create')
def item_add(request):
    categories = fetch_all_categories()
    uom_list = fetch_groups_by_type('UOM')

    if request.method == 'POST':
        # Vendor pattern k mutabiq frontend se post data arrays ko extract kiya
        category_ids = request.POST.getlist('category_id[]')
        names = request.POST.getlist('item_name[]')
        units = request.POST.getlist('unit[]')
        conditions = request.POST.getlist('condition[]')
        descriptions = request.POST.getlist('description[]')
        actives = request.POST.getlist('is_active[]')

        rows = []
        seen = set()
        has_error = False

        for i in range(len(names)):
            name = names[i].strip()
            if not name:
                continue  # Blank rows ko skip karne k liye defensive check

            cat_id = category_ids[i] if i < len(category_ids) else ''
            if not cat_id:
                messages.error(request, f'❌ Category is required for item "{name}".')
                has_error = True
                continue

            # Batch k andar internal duplicate check karne k liye unique combo key (name + category)
            combo_key = f"{name.lower()}_{cat_id}"
            if combo_key in seen:
                messages.error(request, f'❌ Duplicate item "{name}" in the same category within this batch.')
                has_error = True
                continue

            # Database lookup using your existing combo validation function
            if check_duplicate_combo('wst_djn_items', 'ITEM_NAME', name, 'CATEGORY_ID', cat_id):
                messages.error(request, f'❌ Item "{name}" already exists in this category.')
                has_error = True
                continue

            seen.add(combo_key)
            rows.append({
                'category_id': cat_id,
                'name': name,
                'unit': units[i] if i < len(units) else '',
                'condition': conditions[i] if i < len(conditions) else '',
                'description': descriptions[i] if i < len(descriptions) else '',
                'is_active': (actives[i] if i < len(actives) else 'off') == 'on',
            })

        if not rows:
            if not has_error:
                messages.error(request, '❌ Please add at least one item.')
        elif has_error:
            messages.error(request, '❌ Fix the errors above before saving. No items were saved.')
        else:
            try:
                # Loop through validated items array and insert into DB
                for row in rows:
                    insert_item(
                        row['category_id'], 
                        row['name'], 
                        row['unit'], 
                        row['condition'],
                        row['description'], 
                        row['is_active'],
                        username=request.user.username
                    )
                    log_audit('ITEMS', row['name'], 'CREATE', request.user.username)
                
                messages.success(request, f'✅ {len(rows)} item(s) added successfully!')
                return redirect('wastage:item_list')
            except Exception as e:
                messages.error(request, f'❌ Error: {e}')

    existing_items = fetch_all_items()
    return render(request, 'wastage/item_form.html', {
        'title': 'Add Item', 
        'record': None,
        'categories': categories, 
        'uom_list': uom_list,
        'existing_names': [i['ITEM_NAME'] for i in existing_items if i.get('ITEM_NAME')],
    })


@login_required
@page_permission_required('items', action='edit')
def item_edit(request, item_id):
    record = fetch_item_by_id(item_id)
    categories = fetch_all_categories()
    uom_list = fetch_groups_by_type('UOM')

    if not record:
        return redirect('wastage:item_list')

    if request.method == 'POST':
        name = request.POST.get('item_name', '').strip()
        category_id = request.POST.get('category_id', '')

        if not name:
            messages.error(request, '❌ Item name is required.')
        elif not category_id:
            messages.error(request, '❌ Category is required.')
        # Database duplicate combo lookup excluding current editing item ID
        elif check_duplicate_combo('wst_djn_items', 'ITEM_NAME', name, 'CATEGORY_ID', category_id,
                                     exclude_value=item_id, exclude_pk_col='ITEM_ID'):
            messages.error(request, f'❌ Item "{name}" already exists in this category.')
        else:
            try:
                old_data = {'ITEM_NAME': record['ITEM_NAME'], 'UNIT': record['UNIT']}
                new_data = {'ITEM_NAME': name, 'UNIT': request.POST.get('unit', '')}
                
                update_item(
                    item_id, 
                    category_id, 
                    name,
                    request.POST.get('unit', ''), 
                    request.POST.get('condition', ''),
                    request.POST.get('description', ''), 
                    request.POST.get('is_active') == 'on',
                    username=request.user.username
                )
                log_audit('ITEMS', item_id, 'UPDATE', request.user.username, old_data, new_data)
                
                messages.success(request, '✅ Item updated!')
                return redirect('wastage:item_list')
            except Exception as e:
                messages.error(request, f'❌ Error: {e}')

    return render(request, 'wastage/item_form.html', {
        'title': 'Edit Item', 
        'record': record,
        'categories': categories, 
        'uom_list': uom_list
    })


@login_required
@page_permission_required('items', action='delete')
def item_delete(request, item_id):
    if request.method == 'POST':
        try:
            record = fetch_item_by_id(item_id)
            delete_item(item_id, username=request.user.username)
            log_audit('ITEMS', item_id, 'DELETE', request.user.username, record)
            messages.success(request, '✅ Item deleted!')
        except Exception as e:
            messages.error(request, f'❌ Error: {e}')
    return redirect('wastage:item_list')


# ─── MONTHLY STOCK LIST ───────────────────────────────────
@login_required
@login_required
@page_permission_required('monthly_stock_list', action='view')
def stock_list(request):
    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    if sees_all:
        division_filter = request.GET.get('division', 'ALL')
        division = None if division_filter == 'ALL' else division_filter
    else:
        division_filter = user_division
        division = user_division
    return render(request, 'wastage/stock_list.html', {
        'records': fetch_stock_list_summary(division=division),
        'division': user_division,
        'sees_all_divisions': sees_all,
        'division_filter': division_filter,
        'division_choices': _DIVISION_CHOICES,
    })


@login_required
@page_permission_required('monthly_stock_list', action='view')
def msl_snapshot(request):
    """Monthly Stock List (Snapshot-backed): once-per-(division, month)
    permanent archive. Navigating to a month that already has a saved
    snapshot always loads the saved record -- it is NEVER silently
    recalculated. A month with no snapshot yet shows the Generate screen."""
    from datetime import date as date_cls
    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    if sees_all:
        division_filter = request.GET.get('division', user_division)
        division = division_filter
    else:
        division_filter = user_division
        division = user_division

    month_param = request.GET.get('month', '').strip()
    if not month_param:
        month_param = date_cls.today().strftime('%Y-%m')
    target_month = f'{month_param}-01'

    context = {
        'sees_all_divisions': sees_all,
        'division': user_division,
        'division_choices': _DIVISION_CHOICES,
        'division_filter': division_filter,
        'month_param': month_param,
    }

    snapshot = fetch_msl_snapshot_for_month(division, target_month)
    if snapshot:
        context['snapshot'] = snapshot
        context['lines'] = fetch_msl_snapshot_lines(snapshot['SNAPSHOT_ID'])
    else:
        context['snapshot'] = None

    return render(request, 'wastage/msl_snapshot.html', context)

@login_required
@page_permission_required('monthly_stock_list', action='create')
def stock_list_add(request):
    items = fetch_all_items()
    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    if request.method == 'POST':
        item_ids = request.POST.getlist('item_id[]')
        month_years = request.POST.getlist('month_year[]')
        closing_qtys = request.POST.getlist('closing_qty[]')
        conditions = request.POST.getlist('condition[]')
        dispatcheds = request.POST.getlist('dispatched[]')
        divisions = request.POST.getlist('division[]')

        rows = []
        for i in range(len(item_ids)):
            item_id = item_ids[i].strip()
            month_year = month_years[i].strip() if i < len(month_years) else ''
            closing_qty = closing_qtys[i].strip() if i < len(closing_qtys) else ''
            if not item_id or not month_year or not closing_qty:
                continue
            posted_division = divisions[i].strip() if i < len(divisions) else ''
            row_division = posted_division if (sees_all and posted_division in _VALID_DIVISIONS) else user_division
            rows.append({
                'item_id': item_id,
                'month_year': month_year,
                'closing_qty': closing_qty,
                'condition': conditions[i] if i < len(conditions) else '',
                'dispatched': (dispatcheds[i] if i < len(dispatcheds) else 'off') == 'on',
                'division': row_division,
            })

        if not rows:
            messages.error(request, '❌ Please add at least one valid stock entry.')
        else:
            try:
                for row in rows:
                    insert_stock_list(
                        row['item_id'], row['month_year'],
                        row['closing_qty'], row['condition'],
                        row['dispatched'], division=row['division']
                    )
                messages.success(request, f'✅ {len(rows)} stock entry/entries added!')
                return redirect('wastage:stock_list')
            except Exception as e:
                messages.error(request, f'❌ Error: {e}')
    return render(request, 'wastage/stock_list_form.html', {
        'title': 'Add Stock Entry', 'record': None, 'items': items,
        'division': user_division, 'sees_all_divisions': sees_all, 'division_choices': _DIVISION_CHOICES,
    })

@login_required
@page_permission_required('monthly_stock_list', action='edit')
def stock_list_edit(request, list_id):
    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    lookup_division = None if sees_all else user_division
    record = fetch_stock_list_by_id(list_id, division=lookup_division)
    items = fetch_all_items()
    if not record:
        messages.error(request, '❌ Record not found, or it belongs to a different division.')
        return redirect('wastage:stock_list')
    if request.method == 'POST':
        try:
            update_stock_list(
                list_id, request.POST['item_id'], request.POST['month_year'],
                request.POST['closing_qty'], request.POST.get('condition', ''),
                request.POST.get('dispatched') == 'on', division=record['DIVISION']
            )
            messages.success(request, '✅ Stock entry updated!')
            return redirect('wastage:stock_list')
        except Exception as e:
            messages.error(request, f'❌ Error: {e}')
    return render(request, 'wastage/stock_list_form.html', {'title': 'Edit Stock Entry', 'record': record, 'items': items})

@login_required
@page_permission_required('monthly_stock_list', action='delete')
def stock_list_delete(request, list_id):
    if request.method == 'POST':
        sees_all = getattr(request.user, 'sees_all_divisions', False)
        user_division = getattr(request.user, 'division', '08')
        lookup_division = None if sees_all else user_division
        try:
            delete_stock_list(list_id, division=lookup_division)
            messages.success(request, '✅ Deleted!')
        except Exception as e:
            messages.error(request, f'❌ Error: {e}')
    return redirect('wastage:stock_list')


@login_required
@page_permission_required('monthly_stock_list', action='create')
def msl_snapshot_generate(request):
    if request.method == 'POST':
        sees_all = getattr(request.user, 'sees_all_divisions', False)
        user_division = getattr(request.user, 'division', '08')
        division = request.POST.get('division', '').strip() if sees_all else user_division
        if not (sees_all and division in _VALID_DIVISIONS):
            division = user_division
        month_param = request.POST.get('month', '').strip()
        cutoff_date = request.POST.get('cutoff_date', '').strip()
        target_month = f'{month_param}-01'

        if not month_param or not cutoff_date:
            messages.error(request, '❌ A Transaction Cut-off Date is required.')
        else:
            ok, result = generate_msl_snapshot(division, target_month, cutoff_date, username=request.user.username)
            if ok:
                log_audit('MSL_SNAPSHOT', result, 'CREATE', request.user.username)
                messages.success(request, f'✅ Monthly snapshot generated for {month_param}.')
            else:
                messages.error(request, f'❌ {result}')
        return redirect(f"{reverse('wastage:msl_snapshot')}?month={month_param}")
    return redirect('wastage:msl_snapshot')


@login_required
@page_permission_required('monthly_stock_list', action='delete')
def msl_snapshot_delete(request, snapshot_id):
    if request.method == 'POST':
        sees_all = getattr(request.user, 'sees_all_divisions', False)
        user_division = getattr(request.user, 'division', '08')
        lookup_division = None if sees_all else user_division
        month_param = request.POST.get('month', '')
        snap = fetch_msl_snapshot_by_id(snapshot_id, division=lookup_division)
        if not snap:
            messages.error(request, '❌ Snapshot not found, or it belongs to a different division.')
        elif delete_msl_snapshot(snapshot_id, division=lookup_division):
            log_audit('MSL_SNAPSHOT', snapshot_id, 'DELETE', request.user.username)
            messages.success(request, f'✅ Snapshot for {snap["MONTH_DISPLAY"]} permanently deleted. You can now generate a fresh one.')
        else:
            messages.error(request, '❌ Could not delete this snapshot.')
        return redirect(f"{reverse('wastage:msl_snapshot')}?month={month_param}")
    return redirect('wastage:msl_snapshot')


@login_required
@page_permission_required('monthly_stock_list', action='view')
def msl_snapshot_pdf(request, snapshot_id):
    """Exports the SAVED snapshot exactly as stored -- reads from the
    frozen line items, never recalculates from the live ledger, matching
    the immutable-record requirement."""
    from io import BytesIO
    from django.http import HttpResponse
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    lookup_division = None if sees_all else user_division
    snap = fetch_msl_snapshot_by_id(snapshot_id, division=lookup_division)
    if not snap:
        messages.error(request, '❌ Snapshot not found, or it belongs to a different division.')
        return redirect('wastage:msl_snapshot')
    lines = fetch_msl_snapshot_lines(snapshot_id)

    buffer = BytesIO()
    from reportlab.lib.units import mm
    from reportlab.lib.styles import ParagraphStyle
    doc = SimpleDocTemplate(buffer, pagesize=letter,
                             topMargin=8 * mm, bottomMargin=12 * mm,
                             leftMargin=10 * mm, rightMargin=10 * mm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('StockListTitle', parent=styles['Title'],
                                 fontSize=14, leading=16, spaceAfter=0)
    full_w = doc.width  # usable page width after margins
    story = [Paragraph("Stock List", title_style), Spacer(1, 4)]

    meta_data = [
        ['Document No:', snap['DOC_NO'], 'Division:', snap['DIVISION']],
        ['Month:', snap['MONTH_DISPLAY'], 'Created By:', snap['CREATED_BY'] or '—'],
        ['Transaction Date:', snap['CUTOFF_DATE_DISPLAY'], 'Creation Date/Time:', snap['CREATED_DATE']],
    ]
    meta_table = Table(meta_data, colWidths=[full_w * 0.20, full_w * 0.30, full_w * 0.22, full_w * 0.28])
    meta_table.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#334155')),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 6))

    table_data = [['Item Description', 'UOM', 'Quantity']]
    for l in lines:
        table_data.append([l['ITEM_NAME'] or '—', l['UOM'] or '—', f"{(l['CLOSING_BALANCE'] or 0):.2f}"])
    if not lines:
        table_data.append(['No items in this snapshot', '—', '—'])

    item_table = Table(table_data, colWidths=[full_w * 0.70, full_w * 0.10, full_w * 0.20], repeatRows=1)
    item_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#10B981')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E5E7EB')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
    ]))
    story.append(item_table)
    doc.build(story)
    buffer.seek(0)

    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{snap["DOC_NO"]}.pdf"'
    return response


# ─── STOCK LEDGER ─────────────────────────────────────────
@login_required
@page_permission_required('stock_ledger', action='view')
def ledger_list(request):
    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    if sees_all:
        division_filter = request.GET.get('division', 'ALL')
        division = None if division_filter == 'ALL' else division_filter
    else:
        division_filter = user_division
        division = user_division
    # Month choices (last 12 months) for the Export PDF picker.
    import calendar
    from datetime import datetime
    now = datetime.now()
    month_options = []
    for i in range(12):
        m, y = now.month - i, now.year
        if m <= 0:
            m += 12; y -= 1
        month_options.append({'month': m, 'year': y,
                              'label': f"{calendar.month_name[m]} {y}",
                              'selected': i == 0})
    return render(request, 'wastage/ledger_list.html', {
        'records': fetch_all_ledger(division=division),
        'month_options': month_options,
        'division': user_division,
        'sees_all_divisions': sees_all,
        'division_filter': division_filter,
        'division_choices': _DIVISION_CHOICES,
    })

@login_required
@page_permission_required('stock_ledger', action='create')
def ledger_add(request):
    items = fetch_all_items()
    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    if request.method == 'POST':
        posted_division = request.POST.get('division', '').strip()
        division = posted_division if (sees_all and posted_division in _VALID_DIVISIONS) else user_division
        try:
            # Manual entries on this screen are ADJUST only (IN/OUT are
            # posted automatically by Stock Receiving and Gate Pass). The
            # posted "txn_type"/"balance" form values are deliberately
            # ignored: the type is fixed, and balance is always computed.
            post_adjustment(
                request.POST['item_id'], request.POST['txn_date'],
                request.POST.get('qty_in', 0), request.POST.get('qty_out', 0),
                request.POST.get('ref_id'),
                division=division,
                username=request.user.username
            )
            messages.success(request, '✅ Adjustment posted — stock ledger and item balance updated.')
            return redirect('wastage:ledger_list')
        except Exception as e:
            messages.error(request, f'❌ Error: {e}')
    return render(request, 'wastage/ledger_form.html', {
        'title': 'Add Ledger Entry', 'record': None, 'items': items,
        'division': user_division, 'sees_all_divisions': sees_all, 'division_choices': _DIVISION_CHOICES,
        'today': date.today().isoformat(),
    })

@login_required
@page_permission_required('stock_ledger', action='edit')
def ledger_edit(request, ledger_id):
    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    lookup_division = None if sees_all else user_division
    record = fetch_ledger_by_id(ledger_id, division=lookup_division)
    items = fetch_all_items()
    if not record:
        messages.error(request, '❌ Record not found, or it belongs to a different division.')
        return redirect('wastage:ledger_list')
    # Division is set at creation and is immutable afterward — even for
    # privileged users — same rule as Receiving/Sales.
    record_division = record.get('DIVISION', user_division)
    if (record.get('TXN_TYPE') or '').upper() != 'ADJUST':
        messages.error(request, '❌ Only manual Adjust entries can be edited here. '
                                'Receiving and Gate Pass movements are changed from their own screens.')
        return redirect('wastage:ledger_list')
    if request.method == 'POST':
        try:
            update_adjustment(
                ledger_id, request.POST['item_id'], request.POST['txn_date'],
                request.POST.get('qty_in', 0), request.POST.get('qty_out', 0),
                request.POST.get('ref_id'),
                division=record_division,
                username=request.user.username
            )
            messages.success(request, '✅ Adjustment updated — stock ledger and item balance recalculated.')
            return redirect('wastage:ledger_list')
        except Exception as e:
            messages.error(request, f'❌ Error: {e}')
    return render(request, 'wastage/ledger_form.html', {
        'title': 'Edit Ledger Entry', 'record': record, 'items': items, 'division': record_division,
        'today': date.today().isoformat(),
    })

@login_required
@page_permission_required('stock_ledger', action='delete')
def ledger_delete(request, ledger_id):
    sees_all = getattr(request.user, 'sees_all_divisions', False)
    lookup_division = None if sees_all else getattr(request.user, 'division', '08')
    if request.method == 'POST':
        record = fetch_ledger_by_id(ledger_id, division=lookup_division)
        if not record:
            messages.error(request, '❌ Record not found, or it belongs to a different division.')
        else:
            try:
                delete_adjustment(ledger_id, division=record.get('DIVISION', '08'),
                                  username=request.user.username)
                messages.success(request, '✅ Adjustment deleted — stock ledger and item balance recalculated.')
            except Exception as e:
                messages.error(request, f'❌ Error: {e}')
    return redirect('wastage:ledger_list')


@login_required
@page_permission_required('quotations', action='view')
def quotation_header_list(request):
    from datetime import date as date_cls
    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    if sees_all:
        division_filter = request.GET.get('division', 'ALL')
        division = None if division_filter == 'ALL' else division_filter
    else:
        division_filter = user_division
        division = user_division

    # Month dropdown: defaults to the current system month, offers the
    # last 12 months to choose from (same pattern as the Sales list).
    today = date_cls.today()
    month_options = []
    for i in range(12):
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        month_options.append((f'{y:04d}-{m:02d}', date_cls(y, m, 1).strftime('%b %Y')))
    month_param = request.GET.get('month', '').strip() or f'{today.year:04d}-{today.month:02d}'
    target_month = f'{month_param}-01'

    return render(request, 'wastage/quotation_header_list.html', {
        'records': fetch_all_quotation_headers(division=division, month=target_month),
        'division': user_division,
        'sees_all_divisions': sees_all,
        'division_filter': division_filter,
        'division_choices': _DIVISION_CHOICES,
        'month_param': month_param,
        'month_options': month_options,
    })


@login_required
@page_permission_required('quotations', action='view')
def quotation_pdf(request):
    """Same filters as quotation_header_list."""
    from datetime import date as date_cls
    from .pdf_reports import build_quotation_pdf
    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    if sees_all:
        division_filter = request.GET.get('division', 'ALL')
        division = None if division_filter == 'ALL' else division_filter
    else:
        division_filter = user_division
        division = user_division

    today = date_cls.today()
    month_param = request.GET.get('month', '').strip() or f'{today.year:04d}-{today.month:02d}'
    target_month = f'{month_param}-01'

    division_label = 'All Divisions' if division_filter == 'ALL' else (
        dict(_DIVISION_CHOICES).get(division_filter, division_filter))
    month_label = date_cls.fromisoformat(target_month).strftime('%b %Y')

    pdf_bytes = build_quotation_pdf(
        division_label, month_label, division, target_month,
        generated_by=request.user.get_full_name() or request.user.username,
    )
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="quotations_{month_param}.pdf"'
    return response


@login_required
@page_permission_required('quotations', action='view')
def quotation_detail_pdf(request, doc_id):
    """Row-level PDF action: the full header + every line item bid by
    this one vendor on this one document. Distinct from quotation_pdf()
    above, which exports the filtered summary grid across all vendors."""
    import re
    from datetime import date as date_cls
    from .pdf_reports import build_quotation_detail_pdf

    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    lookup_division = None if sees_all else user_division

    header = fetch_quotation_header_by_id(doc_id, division=lookup_division)
    if not header:
        messages.error(request, '❌ Quotation not found, or it belongs to a different division.')
        return redirect('wastage:quotation_list')

    pdf_bytes = build_quotation_detail_pdf(
        doc_id, division=lookup_division,
        generated_by=request.user.get_full_name() or request.user.username,
    )
    if pdf_bytes is None:
        messages.error(request, '❌ Quotation not found, or it belongs to a different division.')
        return redirect('wastage:quotation_list')

    # "Quotation of {Vendor} {Mon} - {YYYY}.pdf" -- vendor name stripped of
    # filesystem-unsafe characters, month taken from the document's own
    # TARGET_MONTH (the quotation's period), not Receive Date, since that's
    # the field that actually labels which month this quotation is for.
    vendor_part = re.sub(r'[\\/:*?"<>|]', '', header.get('VENDOR_NAME') or 'Vendor').strip() or 'Vendor'
    month_dt = date_cls.fromisoformat(str(header['TARGET_MONTH'])[:10])
    filename = f"Quotation of {vendor_part} {month_dt.strftime('%b - %Y')}.pdf"

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
@page_permission_required('quotations', action='create')
def quotation_header_add(request):
    from datetime import date as date_cls
    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    vendors = fetch_all_vendors()
    default_month = date_cls.today().strftime('%Y-%m')

    if request.method == 'POST':
        posted_division = request.POST.get('division', '').strip()
        division = posted_division if (sees_all and posted_division in _VALID_DIVISIONS) else user_division
        month_param = request.POST.get('target_month', '').strip() or default_month
        target_month = f'{month_param}-01'
        vendor_id = request.POST.get('vendor_id')
        receive_date = request.POST.get('receive_date', '').strip()
        valid_until = request.POST.get('valid_until', '').strip()
        remarks = request.POST.get('remarks', '').strip()

        if not vendor_id or not receive_date:
            messages.error(request, '❌ Vendor and Receive Date are required.')
        else:
            available_items, snapshot = fetch_quotation_available_items(division, target_month)
            if not snapshot:
                messages.error(request, f'❌ No Monthly Stock List snapshot exists yet for {month_param} — generate one first before creating a quotation for this period.')
            else:
                try:
                    doc_id = insert_quotation_header(
                        division, target_month, vendor_id, snapshot['DOC_NO'],
                        receive_date, valid_until or None, remarks, username=request.user.username
                    )
                    log_audit('QUOTATION_HEADER', doc_id, 'CREATE', request.user.username)
                    messages.success(request, f'✅ {doc_id} created — add line items below.')
                    header = fetch_quotation_header_by_id(doc_id, division=None if sees_all else user_division)
                    for item in available_items:
                        item['LAST_MONTH_PRICE'] = fetch_last_month_price(item['ITEM_ID'], division, target_month)
                    return render(request, 'wastage/quotation_header_form.html', {
                        'header': header,
                        'lines': [],
                        'available_items': available_items,
                        'next_line_no': 10,
                        'vendors': vendors,
                        'sees_all_divisions': sees_all,
                    })
                except Exception as e:
                    messages.error(request, f'❌ Error: {e}')

    return render(request, 'wastage/quotation_header_add.html', {
        'vendors': vendors, 'division': user_division, 'sees_all_divisions': sees_all,
        'division_choices': _DIVISION_CHOICES, 'default_month': default_month,
        'today': date_cls.today().isoformat(),
    })


@login_required
@page_permission_required('quotations', action='edit')
def quotation_header_edit(request, doc_id):
    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    lookup_division = None if sees_all else user_division
    header = fetch_quotation_header_by_id(doc_id, division=lookup_division)
    if not header:
        messages.error(request, '❌ Quotation not found, or it belongs to a different division.')
        return redirect('wastage:quotation_list')

    is_locked = header.get('STATUS') == 'Locked'
    lines = fetch_quotation_lines(doc_id, division=header['DIVISION'], target_month=header['TARGET_MONTH'])

    if is_locked:
        # Read-only: no point computing what could still be added, since
        # adding/editing/deleting lines is disabled entirely once locked.
        available_items = []
        next_line_no = 0
    else:
        available_items, _snap = fetch_quotation_available_items(header['DIVISION'], header['TARGET_MONTH'])
        already_quoted_ids = {l['ITEM_ID'] for l in lines}
        available_items = [i for i in available_items if i['ITEM_ID'] not in already_quoted_ids]
        for item in available_items:
            item['LAST_MONTH_PRICE'] = fetch_last_month_price(item['ITEM_ID'], header['DIVISION'], header['TARGET_MONTH'])
        next_line_no = max((l['LINE_NO'] for l in lines), default=0) + 10

    return render(request, 'wastage/quotation_header_form.html', {
        'header': header,
        'lines': lines,
        'available_items': available_items,
        'next_line_no': next_line_no,
        'vendors': fetch_all_vendors(),
        'sees_all_divisions': sees_all,
        'is_locked': is_locked,
    })


@login_required
@page_permission_required('quotations', action='edit')
def quotation_lines_bulk_save(request, doc_id):
    """Bulk-saves every row currently staged in the quotation's Add Line
    grid, matching the exact same pattern as Sales' sales_lines_bulk_save.
    All-or-nothing: any invalid row (item not in this month's snapshot,
    already quoted on this header, or missing a price) means NOTHING is
    saved."""
    if request.method != 'POST':
        return redirect('wastage:quotation_header_edit', doc_id=doc_id)

    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    lookup_division = None if sees_all else user_division
    header = fetch_quotation_header_by_id(doc_id, division=lookup_division)
    if not header:
        messages.error(request, '❌ Quotation not found, or it belongs to a different division.')
        return redirect('wastage:quotation_list')
    if header.get('STATUS') == 'Locked':
        messages.error(request, '❌ This quotation is locked and cannot be edited — sales have already been generated from it.')
        return redirect('wastage:quotation_header_edit', doc_id=doc_id)

    available_items, snapshot = fetch_quotation_available_items(header['DIVISION'], header['TARGET_MONTH'])
    available_by_id = {str(i['ITEM_ID']): i for i in available_items}
    existing_lines = fetch_quotation_lines(doc_id)
    already_quoted_ids = {str(l['ITEM_ID']) for l in existing_lines}

    item_ids = request.POST.getlist('item_id[]')
    prices = request.POST.getlist('current_offered_price[]')

    rows = []
    for i in range(len(item_ids)):
        item_id = item_ids[i].strip()
        if not item_id:
            continue
        price = prices[i].strip() if i < len(prices) else ''
        rows.append((item_id, price))

    if not rows:
        return redirect('wastage:quotation_header_edit', doc_id=doc_id)

    seen_this_batch = set()
    for item_id, price in rows:
        if item_id not in available_by_id:
            messages.error(request, '❌ One of the selected items is not part of this month\'s Monthly Stock List — nothing was saved.')
            return redirect('wastage:quotation_header_edit', doc_id=doc_id)
        if item_id in already_quoted_ids or item_id in seen_this_batch:
            item_name = available_by_id[item_id].get('ITEM_NAME', 'this item')
            messages.error(request, f'❌ "{item_name}" is already on this quotation — nothing was saved.')
            return redirect('wastage:quotation_header_edit', doc_id=doc_id)
        if not price:
            messages.error(request, '❌ Every row needs a Current Offered Price — nothing was saved.')
            return redirect('wastage:quotation_header_edit', doc_id=doc_id)
        try:
            float(price)
        except ValueError:
            messages.error(request, '❌ Current Offered Price must be a number — nothing was saved.')
            return redirect('wastage:quotation_header_edit', doc_id=doc_id)
        seen_this_batch.add(item_id)

    try:
        for item_id, price in rows:
            item = available_by_id[item_id]
            insert_quotation_line(
                doc_id, item_id, item['ITEM_CODE'], item['UOM'],
                item['CLOSING_BALANCE'], price
            )
        messages.success(request, f'✅ {len(rows)} line(s) saved.')
    except Exception as e:
        messages.error(request, f'❌ Error saving lines: {e}')

    return redirect('wastage:quotation_header_edit', doc_id=doc_id)


@login_required
@page_permission_required('quotations', action='edit')
def quotation_line_edit_price(request, doc_id, line_id):
    """Edits a single line's offered price in place -- for when a vendor
    revises their bid during negotiation. Matches quotation_line_delete's
    exact guard pattern: division ownership via the header lookup, then
    the LINE's own lock status (not just the header's)."""
    if request.method == 'POST':
        sees_all = getattr(request.user, 'sees_all_divisions', False)
        user_division = getattr(request.user, 'division', '08')
        lookup_division = None if sees_all else user_division
        header = fetch_quotation_header_by_id(doc_id, division=lookup_division)
        if not header:
            messages.error(request, '❌ Quotation not found, or it belongs to a different division.')
        else:
            new_price = request.POST.get('current_offered_price', '').strip()
            if not new_price:
                messages.error(request, '❌ Offered Price is required.')
            else:
                try:
                    float(new_price)
                except ValueError:
                    messages.error(request, '❌ Offered Price must be a number.')
                else:
                    if update_quotation_line_price(line_id, doc_id, new_price):
                        messages.success(request, '✅ Offered price updated.')
                    else:
                        messages.error(request, '❌ This line is locked and cannot be edited — sales have already been generated from it.')
    return redirect('wastage:quotation_header_edit', doc_id=doc_id)


@login_required
@page_permission_required('quotations', action='edit')
def quotation_line_delete(request, doc_id, line_id):
    if request.method == 'POST':
        sees_all = getattr(request.user, 'sees_all_divisions', False)
        user_division = getattr(request.user, 'division', '08')
        lookup_division = None if sees_all else user_division
        header = fetch_quotation_header_by_id(doc_id, division=lookup_division)
        if not header:
            messages.error(request, '❌ Quotation not found, or it belongs to a different division.')
        elif header.get('STATUS') == 'Locked':
            messages.error(request, '❌ This quotation is locked and cannot be edited — sales have already been generated from it.')
        elif delete_quotation_line(line_id, doc_id):
            messages.success(request, '✅ Line removed.')
        else:
            messages.error(request, '❌ Could not remove this line.')
    return redirect('wastage:quotation_header_edit', doc_id=doc_id)


@login_required
@page_permission_required('quotations', action='delete')
def quotation_header_delete(request, doc_id):
    if request.method == 'POST':
        sees_all = getattr(request.user, 'sees_all_divisions', False)
        user_division = getattr(request.user, 'division', '08')
        lookup_division = None if sees_all else user_division
        header = fetch_quotation_header_by_id(doc_id, division=lookup_division)
        if not header:
            messages.error(request, '❌ Quotation not found, or it belongs to a different division.')
        elif header.get('STATUS') == 'Locked':
            messages.error(request, '❌ This quotation is locked and cannot be deleted — sales have already been generated from it.')
        elif delete_quotation_header(doc_id, division=lookup_division):
            log_audit('QUOTATION_HEADER', doc_id, 'DELETE', request.user.username)
            messages.success(request, f'✅ {doc_id} deleted.')
        else:
            messages.error(request, '❌ Could not delete this quotation.')
    return redirect('wastage:quotation_list')


def _prev_month_str(target_month):
    """target_month is 'YYYY-MM-01' (or any day of that month) -> returns
    the same format for the month immediately before it."""
    from datetime import date as date_cls
    d = date_cls.fromisoformat(str(target_month)[:10])
    if d.month == 1:
        prev = date_cls(d.year - 1, 12, 1)
    else:
        prev = date_cls(d.year, d.month - 1, 1)
    return prev.isoformat()


@login_required
@page_permission_required('quotation_comparison', action='view')
def quotation_comparison(request):
    """Quotation Comparison: for a given division+month, shows every item
    that received at least one bid, ranks the bidders, and surfaces
    Last Month Winner / Yearly High / system Best Bid alongside a manual
    override control."""
    from datetime import date as date_cls
    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    if sees_all:
        division_filter = request.GET.get('division', user_division)
        division = division_filter
    else:
        division_filter = user_division
        division = user_division

    month_param = request.GET.get('month', '').strip()
    if not month_param:
        month_param = date_cls.today().strftime('%Y-%m')
    target_month = f'{month_param}-01'

    # Derived columns (VENDOR1/2/3, Last Month Winner, Yearly High, Best
    # Bid, effective selection) now come from the shared builder in
    # oracle_data.py, so the PDF export renders from the identical rows
    # instead of its own second copy of this logic.
    items = build_comparison_rows(division, target_month)

    has_unlocked_items = any(not item['IS_LOCKED'] for item in items)

    return render(request, 'wastage/quotation_comparison.html', {
        'sees_all_divisions': sees_all,
        'division': user_division,
        'division_choices': _DIVISION_CHOICES,
        'division_filter': division_filter,
        'month_param': month_param,
        'items': items,
        'has_unlocked_items': has_unlocked_items,
    })


@login_required
@page_permission_required('quotation_comparison', action='view')
def quotation_comparison_pdf(request):
    """Same filters as quotation_comparison -- note this page (unlike the
    other 4) always resolves to one specific division, never an 'All
    Divisions' option, so the label logic here is simpler."""
    from datetime import date as date_cls
    from .pdf_reports import build_quotation_comparison_pdf
    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    if sees_all:
        division_filter = request.GET.get('division', user_division)
        division = division_filter
    else:
        division_filter = user_division
        division = user_division

    month_param = request.GET.get('month', '').strip()
    if not month_param:
        month_param = date_cls.today().strftime('%Y-%m')
    target_month = f'{month_param}-01'

    division_label = dict(_DIVISION_CHOICES).get(division, division)
    month_label = date_cls.fromisoformat(target_month).strftime('%b %Y')
    # No comparison document/PK exists for this grid -- it's identified by
    # Division + Target Month, not a stored header row -- so the
    # "Comparison ID" the spec asks for is synthesized from those two
    # filters. Built once here so the filename and the reference printed
    # inside the PDF are guaranteed to match.
    reference_no = f'{division}-{month_param}'
    today_str = date_cls.today().strftime('%Y%m%d')

    pdf_bytes = build_quotation_comparison_pdf(
        division_label, month_label, division, target_month,
        generated_by=request.user.get_full_name() or request.user.username,
        reference_no=reference_no,
    )
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = (
        f'attachment; filename="Quotation_Comparison_{reference_no}_{today_str}.pdf"'
    )
    return response


@login_required
@page_permission_required('quotation_comparison', action='edit')
def quotation_lock_and_generate_sales(request):
    """Routes every checked item to a vendor-wise Sales Header/Line, then
    locks every quotation for this division+month. All-or-nothing and
    can't be triggered twice for the same period -- see
    generate_sales_from_comparison() for the atomicity and duplicate-
    prevention details."""
    if request.method != 'POST':
        return redirect('wastage:quotation_comparison')

    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    division = request.POST.get('division', '').strip() if sees_all else user_division
    if not (sees_all and division in _VALID_DIVISIONS):
        division = user_division
    month_param = request.POST.get('month', '').strip()
    target_month = f'{month_param}-01'

    item_ids = request.POST.getlist('selected_item_id[]')
    vendor_ids = request.POST.getlist('selected_vendor_id[]')
    quantities = request.POST.getlist('selected_quantity[]')
    prices = request.POST.getlist('selected_price[]')

    selections = []
    for i in range(len(item_ids)):
        if not item_ids[i]:
            continue
        selections.append({
            'item_id': item_ids[i],
            'vendor_id': vendor_ids[i],
            'quantity': quantities[i],
            'price': prices[i],
        })

    ok, result = generate_sales_from_comparison(division, target_month, selections, username=request.user.username)
    if ok:
        try:
            # FIX: was 'LOCK_AND_GENERATE_SALES' (23 chars) -- ACTION is
            # VARCHAR2(10) in wst_djn_audit_log, so this always raised
            # ORA-12899 after the real lock/generate work had already
            # committed successfully, exactly like the manual-no bug below.
            log_audit('QUOTATION_COMPARISON', target_month, 'LOCK_SALE', request.user.username)
        except Exception as e:
            # The sales themselves are already committed by this point --
            # audit logging is a secondary concern, so a failure here
            # (e.g. a transient connection issue on this separate audit
            # connection) must never surface as an error to the user when
            # the actual operation they asked for already succeeded.
            import logging
            logging.getLogger('wastage').warning(f'Audit log failed after successful Lock & Generate Sales for {target_month}: {e}')
        messages.success(request, f'✅ Locked this period and generated {len(result)} sales document(s): {", ".join(result)}.')
    else:
        messages.error(request, f'❌ {result}')

    redirect_url = reverse('wastage:quotation_comparison')
    qs = f'?month={month_param}'
    if sees_all:
        qs += f'&division={division}'
    return redirect(redirect_url + qs)


@login_required
@page_permission_required('quotation_comparison', action='edit')
def quotation_comparison_unlock(request):
    """Manual 'Unlock' action for a single item on the Comparison grid --
    see unlock_comparison_item() for exactly what this does and does not
    touch (it deliberately refuses if the item's sales doc has already
    been Ship & Posted, rather than silently overlapping with the
    shipment-cancel reversal path)."""
    if request.method != 'POST':
        return redirect('wastage:quotation_comparison')

    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    division = request.POST.get('division', '').strip() if sees_all else user_division
    if not (sees_all and division in _VALID_DIVISIONS):
        division = user_division
    month_param = request.POST.get('month', '').strip()
    target_month = f'{month_param}-01'
    item_id = request.POST.get('item_id', '').strip()

    if not item_id:
        messages.error(request, '❌ No item specified.')
    else:
        ok, err = unlock_comparison_item(item_id, division, target_month, username=request.user.username)
        if ok:
            log_audit('QUOTATION_COMPARISON', f'{item_id}@{target_month}', 'UNLOCK', request.user.username)
            messages.success(request, f'✅ Item unlocked \u2014 vendor selection released, available to lock again.')
        else:
            messages.error(request, f'❌ {err}')

    redirect_url = reverse('wastage:quotation_comparison')
    qs = f'?month={month_param}'
    if sees_all:
        qs += f'&division={division}'
    return redirect(redirect_url + qs)


@login_required
@page_permission_required('quotation_comparison', action='edit')
def quotation_comparison_select(request):
    if request.method == 'POST':
        sees_all = getattr(request.user, 'sees_all_divisions', False)
        user_division = getattr(request.user, 'division', '08')
        division = request.POST.get('division', '').strip() if sees_all else user_division
        if not (sees_all and division in _VALID_DIVISIONS):
            division = user_division
        month_param = request.POST.get('month', '').strip()
        target_month = f'{month_param}-01'
        item_id = request.POST.get('item_id', '').strip()
        vendor_id = request.POST.get('vendor_id', '').strip()
        price = request.POST.get('price', '').strip()

        if item_id and vendor_id and price:
            try:
                save_comparison_selection(item_id, division, target_month, vendor_id, price, username=request.user.username)
                # FIX: was 'SELECT_WINNER' (13 chars, over the 10-char
                # ACTION column limit) -- same ORA-12899 pattern.
                log_audit('QUOTATION_COMPARISON', item_id, 'SELECT_WIN', request.user.username)
                messages.success(request, '✅ Selection saved.')
            except Exception as e:
                messages.error(request, f'❌ Error: {e}')
        return redirect(f"{reverse('wastage:quotation_comparison')}?month={month_param}")
    return redirect('wastage:quotation_comparison')


# ─── VENDOR ASSIGNMENT ────────────────────────────────────
@login_required
@page_permission_required('vendor_assignments', action='view')
def assignment_list(request):
    return render(request, 'wastage/assignment_list.html', {'records': fetch_all_assignments()})

@login_required
@page_permission_required('vendor_assignments', action='create')
def assignment_add(request):
    vendors = fetch_all_vendors()
    items = fetch_all_items()
    stock_lists = fetch_all_stock_list()
    quotations = fetch_all_quotations()
    if request.method == 'POST':
        try:
            insert_assignment(
                request.POST['list_id'], request.POST['vendor_id'],
                request.POST['item_id'], request.POST.get('quote_id'),
                request.POST['assigned_qty'], request.POST['agreed_rate'],
                request.POST['assigned_date']
            )
            messages.success(request, '✅ Assignment added!')
            return redirect('wastage:assignment_list')
        except Exception as e:
            messages.error(request, f'❌ Error: {e}')
    return render(request, 'wastage/assignment_form.html', {
        'title': 'Add Assignment', 'record': None,
        'vendors': vendors, 'items': items,
        'stock_lists': stock_lists, 'quotations': quotations,
        'today': date.today().isoformat(),
    })

@login_required
@page_permission_required('vendor_assignments', action='edit')
def assignment_edit(request, assign_id):
    record = fetch_assignment_by_id(assign_id)
    vendors = fetch_all_vendors()
    items = fetch_all_items()
    stock_lists = fetch_all_stock_list()
    quotations = fetch_all_quotations()
    if not record:
        return redirect('wastage:assignment_list')
    if request.method == 'POST':
        try:
            update_assignment(
                assign_id, request.POST['list_id'], request.POST['vendor_id'],
                request.POST['item_id'], request.POST.get('quote_id'),
                request.POST['assigned_qty'], request.POST['agreed_rate'],
                request.POST['assigned_date']
            )
            messages.success(request, '✅ Assignment updated!')
            return redirect('wastage:assignment_list')
        except Exception as e:
            messages.error(request, f'❌ Error: {e}')
    return render(request, 'wastage/assignment_form.html', {
        'title': 'Edit Assignment', 'record': record,
        'vendors': vendors, 'items': items,
        'stock_lists': stock_lists, 'quotations': quotations,
        'today': date.today().isoformat(),
    })

@login_required
@page_permission_required('vendor_assignments', action='delete')
def assignment_delete(request, assign_id):
    if request.method == 'POST':
        try:
            delete_assignment(assign_id)
            messages.success(request, '✅ Deleted!')
        except Exception as e:
            messages.error(request, f'❌ Error: {e}')
    return redirect('wastage:assignment_list')


# ─── STOCK RECEIVING ──────────────────────────────────────
@login_required
@page_permission_required('stock_receiving', action='view')
def receiving_list(request):
    from datetime import datetime
    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    if sees_all:
        # Privileged user: honor an explicit ?division= filter, default to ALL (no filter)
        division_filter = request.GET.get('division', 'ALL')
        division = None if division_filter == 'ALL' else division_filter
    else:
        # Regular user: locked to their own division, never overridable via request params
        division_filter = user_division
        division = user_division
    now = datetime.now()
    period = request.GET.get('period', f'{now.month}-{now.year}')
    try:
        month, year = period.split('-')
    except ValueError:
        month, year = str(now.month), str(now.year)
    search = request.GET.get('q', '').strip()

    # Build "last 12 months" options for the period dropdown (matches Stock Ledger's picker)
    import calendar
    period_options = []
    for i in range(12):
        m = now.month - i
        y = now.year
        if m <= 0:
            m += 12
            y -= 1
        period_options.append({
            'value': f'{m}-{y}',
            'label': f'{calendar.month_abbr[m]} {y}',
            'selected': (str(m) == str(month) and str(y) == str(year)),
        })

    return render(request, 'wastage/receiving_list.html', {
        'records': fetch_all_receiving(search=search if search else None,
                                        division=division, month=month, year=year),
        'search': search,
        'division': user_division,
        'sees_all_divisions': sees_all,
        'division_choices': _DIVISION_CHOICES,
        'division_filter': division_filter,
        'period_options': period_options,
        'selected_period': f'{month}-{year}',
        'export_departments': fetch_all_departments(),
        'export_items': fetch_all_items(),
    })


@login_required
@page_permission_required('stock_receiving', action='view')
def receiving_pdf(request):
    """Same base filters as receiving_list (division/period/search) PLUS
    the export-modal's own Department/Item (multi-select) and Date Range
    filters, all optional -- Export PDF still reflects the screen's
    division/period by default, the modal adds finer-grained filtering
    on top rather than replacing it."""
    from datetime import datetime
    import calendar
    from .pdf_reports import build_receiving_pdf
    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    if sees_all:
        division_filter = request.GET.get('division', 'ALL')
        division = None if division_filter == 'ALL' else division_filter
    else:
        division_filter = user_division
        division = user_division
    now = datetime.now()
    period = request.GET.get('period', f'{now.month}-{now.year}')
    try:
        month, year = period.split('-')
    except ValueError:
        month, year = str(now.month), str(now.year)
    search = request.GET.get('q', '').strip()

    department_ids = [d for d in request.GET.getlist('department_id[]') if d.strip()]
    item_ids = [i for i in request.GET.getlist('item_id[]') if i.strip()]
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()

    department_labels = None
    if department_ids:
        all_depts = {str(d['DEPT_ID']): d['DEPT_NAME'] for d in fetch_all_departments()}
        department_labels = [all_depts.get(d, d) for d in department_ids]
    item_labels = None
    if item_ids:
        all_items = {str(i['ITEM_ID']): i['ITEM_NAME'] for i in fetch_all_items()}
        item_labels = [all_items.get(i, i) for i in item_ids]

    division_label = 'All Divisions' if division_filter == 'ALL' else (
        dict(_DIVISION_CHOICES).get(division_filter, division_filter))
    month_label = f'{calendar.month_abbr[int(month)]} {year}'

    pdf_bytes = build_receiving_pdf(
        division_label, month_label, search if search else None,
        division, month, year, generated_by=request.user.get_full_name() or request.user.username,
        department_ids=department_ids or None, department_labels=department_labels,
        item_ids=item_ids or None, item_labels=item_labels,
        date_from=date_from or None, date_to=date_to or None,
    )
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="stock_receiving_{month}_{year}.pdf"'
    return response

@login_required
@page_permission_required('stock_receiving', action='create')
def receiving_add(request):
    items = fetch_all_items()
    departments = fetch_all_departments()
    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    VALID_DIVISIONS = _VALID_DIVISIONS
    if request.method == 'POST':
        item_ids = request.POST.getlist('item_id[]')
        dept_ids = request.POST.getlist('dept_id[]')
        received_bys = request.POST.getlist('received_by[]')
        receive_dates = request.POST.getlist('receive_date[]')
        qtys = request.POST.getlist('qty_received[]')
        remarks_list = request.POST.getlist('remarks[]')
        # Only read a submitted division per row if this user actually has the
        # right to choose one — a regular user's POST division is never trusted.
        divisions_posted = request.POST.getlist('division[]') if sees_all else []

        rows = []
        has_error = False
        for i in range(len(item_ids)):
            item_id = (item_ids[i] or '').strip()
            rdate = (receive_dates[i] if i < len(receive_dates) else '').strip()
            qty = (qtys[i] if i < len(qtys) else '').strip()
            # Skip fully-blank rows defensively
            if not item_id and not rdate and not qty:
                continue
            if not item_id:
                messages.error(request, f'❌ Row {i + 1}: Item is required.')
                has_error = True
                continue
            if not rdate:
                messages.error(request, f'❌ Row {i + 1}: Receive date is required.')
                has_error = True
                continue
            if not qty:
                messages.error(request, f'❌ Row {i + 1}: Qty received is required.')
                has_error = True
                continue
            if sees_all:
                row_division = divisions_posted[i] if i < len(divisions_posted) else ''
                row_division = row_division if row_division in VALID_DIVISIONS else user_division
            else:
                row_division = user_division  # locked — client input ignored entirely
            rows.append({
                'item_id': item_id,
                'division': row_division,
                'dept_id': dept_ids[i] if i < len(dept_ids) else '',
                'received_by': received_bys[i] if i < len(received_bys) else '',
                'receive_date': rdate,
                'qty_received': qty,
                'remarks': remarks_list[i] if i < len(remarks_list) else '',
            })

        if not rows:
            if not has_error:
                messages.error(request, '❌ Please add at least one entry.')
        elif has_error:
            messages.error(request, '❌ Fix the errors above before saving. No entries were saved.')
        else:
            try:
                ledger_failures = []
                for row in rows:
                    _, ledger_err = insert_receiving(
                        row['item_id'], row['dept_id'], row['received_by'],
                        row['receive_date'], row['qty_received'], row['remarks'],
                        division=row['division'],
                        username=request.user.username
                    )
                    if ledger_err:
                        ledger_failures.append(ledger_err)
                messages.success(request, f'✅ {len(rows)} receiving entry(ies) added!')
                if ledger_failures:
                    messages.warning(request,
                        f'⚠️ Saved, but the Stock Ledger auto-post FAILED: {ledger_failures[0]}')
                return redirect('wastage:receiving_list')
            except Exception as e:
                messages.error(request, f'❌ Error: {e}')
    return render(request, 'wastage/receiving_form.html', {
        'title': 'Add Stock Receiving', 'record': None,
        'items': items, 'departments': departments, 'division': user_division,
        'sees_all_divisions': sees_all, 'division_choices': _DIVISION_CHOICES,
    })

@login_required
@page_permission_required('stock_receiving', action='edit')
def receiving_edit(request, receive_id):
    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    lookup_division = None if sees_all else user_division  # None = no ownership restriction
    record = fetch_receiving_by_id(receive_id, division=lookup_division)
    items = fetch_all_items()
    departments = fetch_all_departments()
    if not record:
        messages.error(request, '❌ Record not found, or it belongs to a different division.')
        return redirect('wastage:receiving_list')
    # Division is set at creation and is immutable afterward — even for privileged
    # users — since the ledger already posted against the original division.
    record_division = record.get('DIVISION', user_division)
    if request.method == 'POST':
        try:
            success, error = update_receiving(
                receive_id, request.POST['item_id'], request.POST.get('dept_id'),
                request.POST.get('received_by'), request.POST['receive_date'],
                request.POST['qty_received'], request.POST.get('remarks', ''),
                division=record_division, username=request.user.username
            )
            if success:
                messages.success(request, '✅ Receiving entry updated!')
                return redirect('wastage:receiving_list')
            else:
                # A clean, fail-closed rejection (e.g. would drive a
                # balance negative) -- nothing was written, so stay on
                # the edit form rather than redirecting away as if it
                # had succeeded.
                messages.error(request, f'❌ {error}')
        except Exception as e:
            messages.error(request, f'❌ Error: {e}')
    return render(request, 'wastage/receiving_form.html', {
        'title': 'Edit Stock Receiving', 'record': record,
        'items': items, 'departments': departments, 'division': record_division,
    })

@login_required
@page_permission_required('stock_receiving', action='delete')
def receiving_delete(request, receive_id):
    sees_all = getattr(request.user, 'sees_all_divisions', False)
    lookup_division = None if sees_all else getattr(request.user, 'division', '08')
    if request.method == 'POST':
        record = fetch_receiving_by_id(receive_id, division=lookup_division)
        if not record:
            messages.error(request, '❌ Record not found, or it belongs to a different division.')
        else:
            try:
                success, error = delete_receiving(receive_id, division=lookup_division, username=request.user.username)
                if success:
                    messages.success(request, '✅ Deleted!')
                else:
                    # A clean, fail-closed rejection (e.g. would drive a
                    # balance negative) -- nothing was deleted.
                    messages.error(request, f'❌ {error}')
            except Exception as e:
                messages.error(request, f'❌ Error: {e}')
    return redirect('wastage:receiving_list')


# ─── SALES ────────────────────────────────────────────────
@login_required
@page_permission_required('sales_orders', action='view')
def sales_header_list(request):
    from datetime import date as date_cls
    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    search = request.GET.get('q', '').strip()
    if sees_all:
        division_filter = request.GET.get('division', 'ALL')
        division = None if division_filter == 'ALL' else division_filter
    else:
        division_filter = user_division
        division = user_division

    # Month dropdown: defaults to the current system month, offers the
    # last 12 months to choose from (matching the "Dropdown Selection"
    # requirement -- discrete month options, not a free date picker).
    today = date_cls.today()
    month_options = []
    for i in range(12):
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        month_options.append((f'{y:04d}-{m:02d}', date_cls(y, m, 1).strftime('%b %Y')))
    month_param = request.GET.get('month', '').strip() or f'{today.year:04d}-{today.month:02d}'
    target_month = f'{month_param}-01'

    return render(request, 'wastage/sales_header_list.html', {
        'records': fetch_all_sales_headers(division=division, search=search if search else None, month=target_month),
        'search': search,
        'division': user_division,
        'sees_all_divisions': sees_all,
        'division_filter': division_filter,
        'division_choices': _DIVISION_CHOICES,
        'month_param': month_param,
        'month_options': month_options,
    })


@login_required
@page_permission_required('sales_orders', action='view')
def sales_pdf(request):
    """Same filters as sales_header_list."""
    from datetime import date as date_cls
    from .pdf_reports import build_sales_pdf
    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    search = request.GET.get('q', '').strip()
    if sees_all:
        division_filter = request.GET.get('division', 'ALL')
        division = None if division_filter == 'ALL' else division_filter
    else:
        division_filter = user_division
        division = user_division

    today = date_cls.today()
    month_param = request.GET.get('month', '').strip() or f'{today.year:04d}-{today.month:02d}'
    target_month = f'{month_param}-01'

    division_label = 'All Divisions' if division_filter == 'ALL' else (
        dict(_DIVISION_CHOICES).get(division_filter, division_filter))
    month_label = date_cls.fromisoformat(target_month).strftime('%b %Y')

    pdf_bytes = build_sales_pdf(
        division_label, month_label, search if search else None, division, target_month,
        generated_by=request.user.get_full_name() or request.user.username,
    )
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="sales_order_{month_param}.pdf"'
    return response


@login_required
@page_permission_required('sales_orders', action='view')
def sales_detail_pdf(request, doc_id):
    """Row-level PDF action: the full header + every line item on this
    one sale document. Distinct from sales_pdf() above, which exports
    the filtered summary grid across all documents for a month."""
    import re
    from datetime import date as date_cls
    from .pdf_reports import build_sales_detail_pdf

    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    lookup_division = None if sees_all else user_division

    header = fetch_sales_header_by_id(doc_id, division=lookup_division)
    if not header:
        messages.error(request, '❌ Document not found, or it belongs to a different division.')
        return redirect('wastage:sales_list')

    pdf_bytes = build_sales_detail_pdf(
        doc_id, division=lookup_division,
        generated_by=request.user.get_full_name() or request.user.username,
    )
    if pdf_bytes is None:
        messages.error(request, '❌ Document not found, or it belongs to a different division.')
        return redirect('wastage:sales_list')

    # "Sales Order of {Vendor} {Mon} - {YYYY}.pdf" -- same naming convention
    # as the Quotation row-level PDF. Sales headers have no separate "target
    # month" field like Quotations do, so Doc Date drives the month/year here.
    vendor_part = re.sub(r'[\\/:*?"<>|]', '', header.get('VENDOR_NAME') or 'Vendor').strip() or 'Vendor'
    doc_dt = date_cls.fromisoformat(str(header['DOC_DATE'])[:10])
    filename = f"Sales Order of {vendor_part} {doc_dt.strftime('%b - %Y')}.pdf"

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
@page_permission_required('sales_orders', action='create')
def sales_header_add(request):
    vendors = fetch_all_vendors()
    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    if request.method == 'POST':
        vendor_id = request.POST.get('vendor_id')
        doc_date = request.POST.get('doc_date')
        invoice_no = request.POST.get('invoice_no', '').strip()
        posted_division = request.POST.get('division', '').strip()
        division = posted_division if (sees_all and posted_division in _VALID_DIVISIONS) else user_division
        if not vendor_id or not doc_date:
            messages.error(request, '\u274c Vendor and Document Date are required.')
        else:
            try:
                doc_id = insert_sales_header_draft(vendor_id, doc_date, invoice_no, division,
                                                    username=request.user.username)
                log_audit('SALES_HEADER', doc_id, 'CREATE', request.user.username)
                messages.success(request, f'\u2705 Draft {doc_id} created \u2014 add line items below.')
                # Render the Lines section right here, in the SAME response, instead of
                # redirecting to a different URL. The browser's address bar stays on
                # /wastage/sales/add/ -- the Sale Order Lines section simply appears
                # below because this same render() call now has a real header + lines
                # (empty, for a brand new draft) to show, reusing the exact same
                # sales_header_form.html template that sales_header_edit uses.
                lookup_division = None if sees_all else user_division
                header = fetch_sales_header_by_id(doc_id, division=lookup_division)
                return render(request, 'wastage/sales_header_form.html', {
                    'header': header,
                    'lines': fetch_sales_lines(doc_id),
                    'vendors': vendors,
                    'items': fetch_all_items(),
                    'sees_all_divisions': sees_all,
                    'shipment': None,
                })
            except Exception as e:
                messages.error(request, f'\u274c Error: {e}')
    return render(request, 'wastage/sales_header_add.html', {
        'vendors': vendors, 'division': user_division, 'sees_all_divisions': sees_all,
        'division_choices': _DIVISION_CHOICES, 'today': date.today().isoformat(),
    })


@login_required
@page_permission_required('sales_orders', action='edit')
def sales_header_edit(request, doc_id):
    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    lookup_division = None if sees_all else user_division
    header = fetch_sales_header_by_id(doc_id, division=lookup_division)
    if not header:
        messages.error(request, '\u274c Document not found, or it belongs to a different division.')
        return redirect('wastage:sales_list')

    if request.method == 'POST' and header['STATUS'] == 'DRAFT':
        vendor_id = request.POST.get('vendor_id')
        doc_date = request.POST.get('doc_date')
        invoice_no = request.POST.get('invoice_no', '').strip()
        try:
            update_sales_header_draft(doc_id, vendor_id, doc_date, invoice_no,
                                       division=header['DIVISION'], username=request.user.username)
            messages.success(request, '\u2705 Document updated.')
            return redirect('wastage:sales_header_edit', doc_id=doc_id)
        except Exception as e:
            messages.error(request, f'\u274c Error: {e}')
        header = fetch_sales_header_by_id(doc_id, division=lookup_division)

    lines = fetch_sales_lines(doc_id)
    next_line_no = max((l['LINE_NO'] for l in lines), default=0) + 10
    total_pending_qty = sum(float(l['QUANTITY']) - float(l.get('SHIPPED_QTY') or 0) for l in lines)
    return render(request, 'wastage/sales_header_form.html', {
        'header': header,
        'lines': lines,
        'next_line_no': next_line_no,
        'vendors': fetch_all_vendors(),
        'items': fetch_all_items(),
        'sees_all_divisions': sees_all,
        'shipment': fetch_shipment_by_sales_doc_id(doc_id),
        'total_pending_qty': total_pending_qty,
    })


@login_required
@page_permission_required('sales_orders', action='edit')
def sales_line_add(request, doc_id):
    if request.method == 'POST':
        sees_all = getattr(request.user, 'sees_all_divisions', False)
        user_division = getattr(request.user, 'division', '08')
        lookup_division = None if sees_all else user_division
        header = fetch_sales_header_by_id(doc_id, division=lookup_division)
        if not header:
            messages.error(request, '\u274c Document not found, or it belongs to a different division.')
        elif header['STATUS'] != 'DRAFT':
            messages.error(request, '\u274c Only DRAFT documents can have lines added.')
        else:
            item_id = request.POST.get('item_id')
            quantity = request.POST.get('quantity')
            unit_price = request.POST.get('unit_price')
            if not (item_id and quantity and unit_price):
                messages.error(request, '\u274c Item, Quantity, and Unit Price are all required.')
            else:
                item = fetch_item_by_id(item_id)
                item_name = item['ITEM_NAME'] if item else f'Item #{item_id}'
                available = fetch_item_available_balance(item_id, header['DIVISION'])
                requested = float(quantity)
                if available <= 0:
                    messages.error(request, f'\u274c "{item_name}" is out of stock (0 available in Division {header["DIVISION"]}) — this item cannot be added to the sale.')
                elif requested > available:
                    messages.error(request, f'\u274c Insufficient stock for "{item_name}": requested {requested:g}, only {available:g} available in Division {header["DIVISION"]}.')
                else:
                    try:
                        insert_sales_line(doc_id, item_id, quantity, unit_price)
                        messages.success(request, '\u2705 Line added.')
                    except Exception as e:
                        messages.error(request, f'\u274c Error: {e}')
    return redirect('wastage:sales_header_edit', doc_id=doc_id)


@login_required
@page_permission_required('sales_orders', action='edit')
def sales_line_delete(request, doc_id, line_id):
    if request.method == 'POST':
        sees_all = getattr(request.user, 'sees_all_divisions', False)
        user_division = getattr(request.user, 'division', '08')
        lookup_division = None if sees_all else user_division
        header = fetch_sales_header_by_id(doc_id, division=lookup_division)
        if not header:
            messages.error(request, '\u274c Document not found, or it belongs to a different division.')
        elif header['STATUS'] != 'DRAFT':
            messages.error(request, '\u274c Only DRAFT documents can have lines removed.')
        elif not delete_sales_line(line_id, doc_id):
            messages.error(request, '\u274c This line has already shipped against a Gate Pass and can no longer be removed here.')
        else:
            messages.success(request, '\u2705 Line removed.')
    return redirect('wastage:sales_header_edit', doc_id=doc_id)


@login_required
@page_permission_required('sales_orders', action='edit')
def sales_line_edit(request, doc_id, line_id):
    """Edits Quantity and Unit Price on a single existing line. Unlike
    sales_line_delete() above, this does NOT require the header itself
    to still be DRAFT -- a header can be PARTIAL (some other line on it
    has already shipped) while THIS line is still untouched and should
    stay editable. update_sales_line() itself is the real gate: it
    checks the line's OWN status, not the header's."""
    if request.method == 'POST':
        sees_all = getattr(request.user, 'sees_all_divisions', False)
        user_division = getattr(request.user, 'division', '08')
        lookup_division = None if sees_all else user_division
        header = fetch_sales_header_by_id(doc_id, division=lookup_division)
        if not header:
            messages.error(request, '\u274c Document not found, or it belongs to a different division.')
        else:
            quantity = request.POST.get('quantity', '').strip()
            unit_price = request.POST.get('unit_price', '').strip()
            ok, error = update_sales_line(line_id, doc_id, quantity, unit_price)
            if ok:
                messages.success(request, '\u2705 Line updated.')
            else:
                messages.error(request, f'\u274c {error}')
    return redirect('wastage:sales_header_edit', doc_id=doc_id)


@login_required
@page_permission_required('sales_orders', action='edit')
def sales_lines_bulk_save(request, doc_id):
    """Saves ALL rows currently staged in the Sale Order Lines grid in one
    request (same bulk-add pattern already used by Category/Item/Vendor/
    Department/Receiving). All-or-nothing: if any row fails validation
    (missing fields or bad numbers), NOTHING is saved. Deliberately does
    NOT check stock availability -- a Sales Order is allowed to book
    beyond current physical stock (backorder), per the requirement that
    booking and fulfillment are governed separately: fulfillment stays
    capped by actual stock, but only at dispatch time (Gate Pass), not
    here at order-entry time.

    RETIRED: this used to also handle action == 'post' -- immediately
    posting via the atomic "Ship and Post" path right after saving.
    Sales Orders are now fulfilled exclusively via Gate Pass, so that
    branch is gone; any 'post' action value submitted (a stale cached
    page, an old bookmark) is now just treated as an ordinary save --
    deliberately not an error, since silently degrading to "just save
    the lines" is safer than either crashing or quietly still posting."""
    if request.method != 'POST':
        return redirect('wastage:sales_header_edit', doc_id=doc_id)

    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    lookup_division = None if sees_all else user_division
    header = fetch_sales_header_by_id(doc_id, division=lookup_division)
    if not header:
        messages.error(request, '❌ Document not found, or it belongs to a different division.')
        return redirect('wastage:sales_list')
    if header['STATUS'] != 'DRAFT':
        messages.error(request, '❌ Only DRAFT documents can have lines added.')
        return redirect('wastage:sales_header_edit', doc_id=doc_id)

    item_ids = request.POST.getlist('item_id[]')
    quantities = request.POST.getlist('quantity[]')
    unit_prices = request.POST.getlist('unit_price[]')

    # Only rows where the user actually picked an item count -- a trailing
    # blank row (auto-generated by Tab but never filled in) is silently
    # ignored rather than treated as an error.
    rows = []
    for i in range(len(item_ids)):
        item_id = item_ids[i].strip()
        if not item_id:
            continue
        quantity = quantities[i].strip() if i < len(quantities) else ''
        unit_price = unit_prices[i].strip() if i < len(unit_prices) else ''
        rows.append((item_id, quantity, unit_price))

    if not rows:
        return redirect('wastage:sales_header_edit', doc_id=doc_id)

    # Validate every row BEFORE saving any of them -- all-or-nothing.
    requested_by_item = {}
    for item_id, quantity, unit_price in rows:
        if not (quantity and unit_price):
            messages.error(request, '❌ Every row needs Quantity and Unit Price — nothing was saved.')
            return redirect('wastage:sales_header_edit', doc_id=doc_id)
        try:
            qty_f = float(quantity)
            price_f = float(unit_price)
        except ValueError:
            messages.error(request, '❌ Quantity and Unit Price must be numbers — nothing was saved.')
            return redirect('wastage:sales_header_edit', doc_id=doc_id)
        if qty_f <= 0:
            messages.error(request, '❌ Quantity must be greater than zero — nothing was saved.')
            return redirect('wastage:sales_header_edit', doc_id=doc_id)
        requested_by_item[item_id] = requested_by_item.get(item_id, 0) + qty_f

    # Stock-availability check REMOVED per the backorder requirement --
    # a Sales Order is now allowed to book beyond current physical
    # stock, with the shortfall scheduled for future production.
    # Fulfillment stays strictly capped by actual stock -- that
    # enforcement already lives at dispatch time, in post_gate_pass()'s
    # own balance check, which is untouched by this change.

    try:
        for item_id, quantity, unit_price in rows:
            insert_sales_line(doc_id, item_id, quantity, unit_price)
        messages.success(request, f'✅ {len(rows)} line(s) saved.')
    except Exception as e:
        messages.error(request, f'❌ Error saving lines: {e}')
        return redirect('wastage:sales_header_edit', doc_id=doc_id)

    return redirect('wastage:sales_header_edit', doc_id=doc_id)


@login_required
@page_permission_required('sales_orders', action='edit')
def sales_header_post(request, doc_id):
    """RETIRED: Sales Orders are now fulfilled exclusively via Gate Pass,
    not this atomic "Ship and Post" path -- see engineering-learnings.md
    for the full retirement decision. Kept as a named view (rather than
    removed outright) purely so this URL, if hit directly by an old
    bookmark or a stale cached page, gives a clear explanation instead
    of a 404 or silently doing the retired action."""
    messages.error(request, '❌ "Ship and Post" has been retired -- Sales Orders are now fulfilled exclusively via Gate Pass.')
    return redirect('wastage:sales_header_edit', doc_id=doc_id)


@login_required
@page_permission_required('shipments', action='view')
def shipment_list(request):
    from datetime import date as date_cls
    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    if sees_all:
        division_filter = request.GET.get('division', 'ALL')
        division = None if division_filter == 'ALL' else division_filter
    else:
        division_filter = user_division
        division = user_division

    status_filter = request.GET.get('status', 'ALL')

    today = date_cls.today()
    month_options = []
    for i in range(12):
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        month_options.append((f'{y:04d}-{m:02d}', date_cls(y, m, 1).strftime('%b %Y')))
    month_param = request.GET.get('month', '').strip() or f'{today.year:04d}-{today.month:02d}'
    target_month = f'{month_param}-01'

    return render(request, 'wastage/shipment_list.html', {
        'records': fetch_all_shipments(division=division, status=status_filter, month=target_month),
        'division': user_division,
        'sees_all_divisions': sees_all,
        'division_filter': division_filter,
        'division_choices': _DIVISION_CHOICES,
        'status_filter': status_filter,
        'month_param': month_param,
        'month_options': month_options,
    })


@login_required
@page_permission_required('shipments', action='delete')
def shipment_cancel(request, ship_doc_id):
    if request.method == 'POST':
        sees_all = getattr(request.user, 'sees_all_divisions', False)
        user_division = getattr(request.user, 'division', '08')
        lookup_division = None if sees_all else user_division
        division = request.POST.get('division') or lookup_division or user_division
        ok, result = cancel_shipment(ship_doc_id, division, username=request.user.username)
        if ok:
            sales_doc_id = result
            log_audit('SHIPMENT', ship_doc_id, 'CANCEL', request.user.username)
            messages.success(request, f'\u2705 {ship_doc_id} cancelled \u2014 stock restored, {sales_doc_id} reopened as DRAFT for editing or re-shipping.')
            return redirect('wastage:sales_header_edit', doc_id=sales_doc_id)
        else:
            messages.error(request, f'\u274c Cancellation failed, nothing was changed: {result}')
    return redirect('wastage:sales_list')


@login_required
@page_permission_required('gate_pass', action='view')
def gatepass_list(request):
    from datetime import date as date_cls
    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    if sees_all:
        division_filter = request.GET.get('division', 'ALL')
        division = None if division_filter == 'ALL' else division_filter
    else:
        division_filter = user_division
        division = user_division

    status_filter = request.GET.get('status', 'ALL')

    today = date_cls.today()
    month_options = []
    for i in range(12):
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        month_options.append((f'{y:04d}-{m:02d}', date_cls(y, m, 1).strftime('%b %Y')))
    month_param = request.GET.get('month', '').strip() or f'{today.year:04d}-{today.month:02d}'
    target_month = f'{month_param}-01'

    return render(request, 'wastage/gatepass_list.html', {
        'records': fetch_all_gate_passes(division=division, status=status_filter, month=target_month),
        'division': user_division,
        'sees_all_divisions': sees_all,
        'division_filter': division_filter,
        'division_choices': _DIVISION_CHOICES,
        'status_filter': status_filter,
        'month_param': month_param,
        'month_options': month_options,
    })


@login_required
@page_permission_required('gate_pass', action='view')
def gatepass_pdf(request):
    """Same filters as gatepass_list."""
    from datetime import date as date_cls
    from .pdf_reports import build_gatepass_pdf
    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    if sees_all:
        division_filter = request.GET.get('division', 'ALL')
        division = None if division_filter == 'ALL' else division_filter
    else:
        division_filter = user_division
        division = user_division

    status_filter = request.GET.get('status', 'ALL')

    today = date_cls.today()
    month_param = request.GET.get('month', '').strip() or f'{today.year:04d}-{today.month:02d}'
    target_month = f'{month_param}-01'

    division_label = 'All Divisions' if division_filter == 'ALL' else (
        dict(_DIVISION_CHOICES).get(division_filter, division_filter))
    status_label = 'All Statuses' if status_filter == 'ALL' else status_filter
    month_label = date_cls.fromisoformat(target_month).strftime('%b %Y')

    pdf_bytes = build_gatepass_pdf(
        division_label, month_label, status_label, division, status_filter, target_month,
        generated_by=request.user.get_full_name() or request.user.username,
    )
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="gate_pass_{month_param}.pdf"'
    return response


@login_required
@page_permission_required('gate_pass', action='view')
def gatepass_detail_pdf(request, gate_pass_id):
    """Row-level PDF action: the full header + every line item on this
    one physical Gate Pass slip, formatted to match the reference Gate
    Pass document. Distinct from gatepass_pdf() above, which exports the
    filtered summary grid across all passes for a month.

    Blocked entirely while the document is still a Draft -- a Draft
    hasn't moved any stock yet, so a printed slip for it would be a
    dispatch document for a shipment that, as far as the ledger is
    concerned, hasn't happened."""
    from .pdf_reports import build_gate_pass_detail_pdf

    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    lookup_division = None if sees_all else user_division

    header = fetch_gate_pass_by_id(gate_pass_id, division=lookup_division)
    if not header:
        messages.error(request, '❌ Gate Pass not found, or it belongs to a different division.')
        return redirect('wastage:gatepass_list')
    if header.get('STATUS') == 'Draft':
        messages.error(request, '❌ This Gate Pass is still a Draft — Ship & Post it first before printing.')
        return redirect('wastage:gatepass_edit', gate_pass_id=gate_pass_id)

    pdf_bytes = build_gate_pass_detail_pdf(
        gate_pass_id, division=lookup_division,
        generated_by=request.user.get_full_name() or request.user.username,
    )
    if pdf_bytes is None:
        messages.error(request, '❌ Gate Pass not found, or it belongs to a different division.')
        return redirect('wastage:gatepass_list')

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="Gate Pass {gate_pass_id}.pdf"'
    return response


@login_required
@page_permission_required('gate_pass', action='delete')
def gatepass_delete(request, gate_pass_id):
    """Same 'Delete' action on the list screen, but genuinely different
    logic depending on the record's actual status:
      Draft     -> hard delete (delete_gate_pass_draft) -- nothing ever
                   moved, nothing to keep.
      Cancelled -> soft archive (archive_gate_pass) -- hides it from
                   the list, but the row and its full ledger trail stay
                   intact for audit, per the explicit decision to
                   preserve that history rather than destroy it.
      anything else (Posted) -> refused outright; must be Cancelled
                   first, this action was never meant to touch a live
                   document."""
    if request.method == 'POST':
        sees_all = getattr(request.user, 'sees_all_divisions', False)
        user_division = getattr(request.user, 'division', '08')
        lookup_division = None if sees_all else user_division
        header = fetch_gate_pass_by_id(gate_pass_id, division=lookup_division)
        if not header:
            messages.error(request, '❌ Gate Pass not found, or it belongs to a different division.')
        elif header.get('STATUS') == 'Draft':
            ok, error = delete_gate_pass_draft(gate_pass_id, header['DIVISION'], username=request.user.username)
            if ok:
                log_audit('GATEPASS', gate_pass_id, 'DELETE', request.user.username)
                messages.success(request, f'✅ Draft {gate_pass_id} deleted.')
            else:
                messages.error(request, f'❌ {error}')
        elif header.get('STATUS') == 'Cancelled':
            ok, error = archive_gate_pass(gate_pass_id, header['DIVISION'], username=request.user.username)
            if ok:
                log_audit('GATEPASS', gate_pass_id, 'ARCHIVE', request.user.username)
                messages.success(request, f'✅ {gate_pass_id} archived — removed from this list, full record kept for audit.')
            else:
                messages.error(request, f'❌ {error}')
        else:
            messages.error(request, f'❌ Only a Draft or a Cancelled Gate Pass can be removed from this list (this one is {header.get("STATUS")}).')
    return redirect('wastage:gatepass_list')


@login_required
@page_permission_required('gate_pass', action='create')
def gatepass_add(request, gate_pass_id=None):
    """Section 3: initial Division/Month/Module selection, then dynamic
    Vendor + open-SO-line loading (Shipment) or direct item entry
    (Transfer). Uses the same GET-param progressive-reveal pattern as
    the rest of this app's filter forms (Division/Month dropdowns that
    resubmit on change) rather than an AJAX-driven cascade, for
    consistency with how every other filtered screen here already works.

    Handles both /gatepass/add/ (gate_pass_id=None, always a fresh
    document) and /gatepass/<id>/edit/ (an existing Draft, loaded for
    continued editing -- refuses and redirects to the read-only detail
    view if that record isn't actually still a Draft, since Posted/
    Cancelled documents aren't edited through this form).

    request.POST['action'] decides Save Draft vs Ship & Post:
      'draft' -> save_gate_pass_draft() -- no stock impact, ever.
      anything else (including missing) -> post_gate_pass() is the
        fallback... except that's exactly the bug this fix closes, so
        the fallback here is deliberately the SAFE direction instead:
        unrecognized/missing action saves as a Draft, not a post. The
        template must send name="action" value="draft" or value="post"
        on the two buttons for the Ship & Post path to actually be
        reachable at all -- until it does, every submission here is
        safe by construction rather than defaulting to the dangerous
        stock-deducting path."""
    from datetime import date as date_cls
    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    division = request.GET.get('division') or user_division
    today = date_cls.today()
    month_param = request.GET.get('month', '').strip() or f'{today.year:04d}-{today.month:02d}'
    module_type = request.GET.get('module_type', '').strip()
    vendor_id = request.GET.get('vendor_id', '').strip()

    lookup_division = None if sees_all else user_division
    existing = None
    existing_lines = []
    if gate_pass_id:
        existing = fetch_gate_pass_by_id(gate_pass_id, division=lookup_division)
        if not existing:
            messages.error(request, '❌ Gate Pass not found, or it belongs to a different division.')
            return redirect('wastage:gatepass_list')
        if existing.get('STATUS') != 'Draft':
            messages.error(request, '❌ Only a Draft can be edited here — view it instead.')
            return redirect('wastage:gatepass_view', gate_pass_id=gate_pass_id)
        division = existing.get('DIVISION') or division
        module_type = module_type or existing.get('MODULE_TYPE', '')
        existing_lines = fetch_gate_pass_lines(gate_pass_id)
        # FIX: editing an existing Shipment-module Draft needs its Party
        # pre-selected too, not just Division/Module -- otherwise the
        # template's own "select a party above" gate (see
        # gatepass_add.html) hides the entire Gate Pass Details form,
        # INCLUDING all its existing_header pre-population, making an
        # edit look exactly like a blank "New Gate Pass" screen. Derived
        # from the existing draft's own lines: any one of them names the
        # Sales Order it's shipping against, and that document's own
        # VENDOR_ID is the Party this Gate Pass was always for.
        if not vendor_id and module_type == 'Shipment':
            first_so_doc_id = next((l['SO_DOC_ID'] for l in existing_lines if l.get('SO_DOC_ID')), None)
            if first_so_doc_id:
                so_header = fetch_sales_header_by_id(first_so_doc_id)
                if so_header and so_header.get('VENDOR_ID'):
                    vendor_id = str(so_header['VENDOR_ID'])

    if request.method == 'POST':
        action = request.POST.get('action', 'draft')  # see docstring: unrecognized/missing defaults to the SAFE path
        module_type = request.POST.get('module_type', '').strip()
        division = request.POST.get('division') or user_division
        item_ids = request.POST.getlist('item_id[]')
        so_line_ids = request.POST.getlist('so_line_id[]')
        so_doc_ids = request.POST.getlist('so_doc_id[]')
        qtys = request.POST.getlist('gatepass_qty[]')
        remarks_list = request.POST.getlist('line_remarks[]')

        lines = []
        for i in range(len(item_ids)):
            qty_str = qtys[i].strip() if i < len(qtys) else ''
            if not qty_str or float(qty_str) <= 0:
                continue
            lines.append({
                'item_id': item_ids[i],
                'so_doc_id': so_doc_ids[i] if i < len(so_doc_ids) and so_doc_ids[i] else None,
                'so_line_id': so_line_ids[i] if i < len(so_line_ids) and so_line_ids[i] else None,
                'gatepass_qty': qty_str,
                'remarks': remarks_list[i] if i < len(remarks_list) else '',
            })

        header = {
            'division': division,
            'module_type': module_type,
            'gate_pass_date': request.POST.get('gate_pass_date') or today.isoformat(),
            'document_type': request.POST.get('document_type') or 'Waste',
            'sender_id': request.POST.get('sender_id') or None,
            'ship_to': request.POST.get('ship_to', '').strip(),
            'sender_department_id': request.POST.get('sender_department_id') or None,
            'vehicle_type': request.POST.get('vehicle_type', '').strip(),
            'vehicle_no': request.POST.get('vehicle_no', '').strip(),
            'driver_name': request.POST.get('driver_name', '').strip(),
            'receiver_name': request.POST.get('receiver_name', '').strip(),
            'remarks': request.POST.get('remarks', '').strip(),
        }

        if not lines:
            messages.error(request, '❌ Select at least one line with a Gate Pass Qty greater than zero.')
        elif action == 'draft':
            ok, result = save_gate_pass_draft(header, lines, gate_pass_id=gate_pass_id, username=request.user.username)
            if ok:
                log_audit('GATEPASS', result, 'DRAFT' if not gate_pass_id else 'DRAFT_UPDATE', request.user.username)
                messages.success(request, f'✅ Draft {result} saved — no stock has been moved. Come back anytime to finish and post it.')
                return redirect('wastage:gatepass_edit', gate_pass_id=result)
            else:
                messages.error(request, f'❌ {result}')
        else:
            ok, result = post_gate_pass(header, lines, gate_pass_id=gate_pass_id, username=request.user.username)
            if ok:
                log_audit('GATEPASS', result, 'POST', request.user.username)
                messages.success(request, f'✅ {result} posted — stock deducted and Sales Order line(s) updated.')
                return redirect('wastage:gatepass_view', gate_pass_id=result)
            else:
                messages.error(request, f'❌ {result}')
        # fall through to re-render the form with whatever was selected, on failure

    # existing_lines was already fetched above (needed there to derive
    # vendor_id) -- reused as-is here, not re-fetched.

    vendors = []
    so_lines = []
    if module_type == 'Shipment':
        target_month = f'{month_param}-01'
        vendors = fetch_vendors_with_open_so(division, target_month)
        if vendor_id:
            exclude_ids = [l['SO_LINE_ID'] for l in existing_lines if l.get('SO_LINE_ID')] if gate_pass_id else None
            so_lines = fetch_open_so_lines_for_vendor(vendor_id, division, target_month, exclude_so_line_ids=exclude_ids)

    all_items = fetch_all_items()
    return render(request, 'wastage/gatepass_add.html', {
        'division': user_division,
        'sees_all_divisions': sees_all,
        'division_choices': _DIVISION_CHOICES,
        'division_selected': division,
        'month_param': month_param,
        'module_type': module_type,
        'vendor_id': vendor_id,
        'vendors': vendors,
        'so_lines': so_lines,
        'senders': fetch_gatepass_senders(),
        'departments': fetch_all_departments(),
        'items': all_items,
        'items_json': json.dumps([{'ITEM_ID': it['ITEM_ID'], 'ITEM_NAME': it['ITEM_NAME']} for it in all_items]),
        'today': today.isoformat(),
        'existing_header': existing,
        'existing_lines': existing_lines,
        'existing_lines_json': json.dumps(existing_lines),
    })


@login_required
@page_permission_required('gate_pass', action='create')
def gatepass_add_sender(request):
    """AJAX endpoint backing the Sender Name dropdown's inline '+' button
    (Section 4). Returns JSON so the dropdown can be updated without a
    full page reload."""
    if request.method == 'POST':
        name = request.POST.get('sender_name', '').strip()
        if not name:
            return JsonResponse({'ok': False, 'error': 'Sender name is required.'})
        new_id = add_gatepass_sender(name, username=request.user.username)
        return JsonResponse({'ok': True, 'sender_id': new_id, 'sender_name': name})
    return JsonResponse({'ok': False, 'error': 'POST required.'})


@login_required
@page_permission_required('gate_pass', action='view')
def gatepass_view(request, gate_pass_id):
    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    lookup_division = None if sees_all else user_division
    header = fetch_gate_pass_by_id(gate_pass_id, division=lookup_division)
    if not header:
        messages.error(request, '\u274c Gate Pass not found, or it belongs to a different division.')
        return redirect('wastage:gatepass_list')
    return render(request, 'wastage/gatepass_view.html', {
        'header': header,
        'lines': fetch_gate_pass_lines(gate_pass_id),
        'sees_all_divisions': sees_all,
        'can_edit_manual_no': has_page_permission(request.user, 'gate_pass', 'manual_gp_no'),
    })


@login_required
@page_permission_required('gate_pass', action='manual_gp_no')
def gatepass_set_manual_no(request, gate_pass_id):
    """Sets the manually-assigned Gate Pass number -- entered by gate/
    security staff once dispatch has actually happened. A separate,
    narrow permission from the rest of Gate Pass editing: this is the
    ONE field meant to still be writable after posting, deliberately
    gated by its own RBAC action so it doesn't require (or imply)
    general Gate Pass edit rights."""
    if request.method == 'POST':
        sees_all = getattr(request.user, 'sees_all_divisions', False)
        user_division = getattr(request.user, 'division', '08')
        lookup_division = None if sees_all else user_division
        manual_no = request.POST.get('manual_gate_pass_no', '')
        ok, err = set_manual_gate_pass_no(gate_pass_id, manual_no, division=lookup_division, username=request.user.username)
        if ok:
            # FIX: confirmed root cause of the "saves but shows Server
            # Error 500" report -- was 'SET_MANUAL_NO' (13 chars). The
            # real update above already committed successfully; this
            # log_audit() call was the one throwing ORA-12899 afterward.
            log_audit('GATEPASS', gate_pass_id, 'MANUAL_NO', request.user.username)
            messages.success(request, f'\u2705 Manual Gate Pass No. saved.')
        else:
            messages.error(request, f'\u274c {err}')
    return redirect('wastage:gatepass_view', gate_pass_id=gate_pass_id)


@login_required
@page_permission_required('gate_pass', action='cancel')
def gatepass_cancel(request, gate_pass_id):
    if request.method == 'POST':
        sees_all = getattr(request.user, 'sees_all_divisions', False)
        user_division = getattr(request.user, 'division', '08')
        lookup_division = None if sees_all else user_division
        division = request.POST.get('division') or lookup_division or user_division
        ok, result = cancel_gate_pass(gate_pass_id, division, username=request.user.username)
        if ok:
            log_audit('GATEPASS', gate_pass_id, 'CANCEL', request.user.username)
            messages.success(request, f'\u2705 {gate_pass_id} cancelled \u2014 stock restored, Sales Order line(s) rolled back.')
        else:
            messages.error(request, f'\u274c Cancellation failed, nothing was changed: {result}')
    return redirect('wastage:gatepass_view', gate_pass_id=gate_pass_id)


@login_required
@page_permission_required('sales_orders', action='delete')
def sales_header_cancel(request, doc_id):
    if request.method == 'POST':
        sees_all = getattr(request.user, 'sees_all_divisions', False)
        user_division = getattr(request.user, 'division', '08')
        lookup_division = None if sees_all else user_division
        header = fetch_sales_header_by_id(doc_id, division=lookup_division)
        if not header:
            messages.error(request, '\u274c Document not found, or it belongs to a different division.')
        else:
            ok, err = cancel_sales_document(doc_id, header['DIVISION'], username=request.user.username)
            if ok:
                log_audit('SALES_HEADER', doc_id, 'CANCEL', request.user.username)
                messages.success(request, f'\u2705 {doc_id} cancelled \u2014 stock restored.')
            else:
                messages.error(request, f'\u274c Cancellation failed, nothing was changed: {err}')
    return redirect('wastage:sales_header_edit', doc_id=doc_id)


@login_required
@page_permission_required('sales_orders', action='delete')
def sales_header_delete(request, doc_id):
    if request.method == 'POST':
        sees_all = getattr(request.user, 'sees_all_divisions', False)
        user_division = getattr(request.user, 'division', '08')
        lookup_division = None if sees_all else user_division
        if delete_sales_header_draft(doc_id, division=lookup_division):
            log_audit('SALES_HEADER', doc_id, 'DELETE', request.user.username)
            messages.success(request, f'\u2705 {doc_id} deleted.')
        else:
            messages.error(request, '\u274c Only DRAFT documents can be deleted, or it belongs to a different division.')
    return redirect('wastage:sales_list')


@login_required
@page_permission_required('whatsapp_log', action='view')
def whatsapp_list(request):
    return render(request, 'wastage/whatsapp_list.html', {'records': fetch_all_whatsapp_logs()})




# ─── USER GENERIC GROUP TYPE ──────────────────────────────
@login_required
@page_permission_required('group_types', action='view')
def group_type_list(request):
    search = request.GET.get('q', '').strip()
    page = int(request.GET.get('page', 1))
    page_size = 7

    group_types, total = fetch_group_types_paginated(
        search=search if search else None, page=page, page_size=page_size
    )
    for gt in group_types:
        gt['children'] = fetch_groups_by_type(gt['GROUP_CODE'])

    total_pages = (total + page_size - 1) // page_size if total > 0 else 1

    return render(request, 'wastage/group_type_list.html', {
        'records': group_types,
        'search': search,
        'page': page,
        'total_pages': total_pages,
        'total_pages_range': range(1, total_pages + 1),
        'total': total,
    })

@login_required
@page_permission_required('group_types', action='create')
def group_type_add(request):
    if request.method == 'POST':
        code = request.POST.get('group_code', '').strip().upper()
        if not code:
            messages.error(request, '❌ Group Code is required.')
        elif check_duplicate('wst_djn_user_generic_group_type', 'GROUP_CODE', code):
            messages.error(request, f'❌ Group Code "{code}" already exists.')
        else:
            try:
                insert_group_type(code, request.POST.get('short_desc', ''), username=request.user.username)
                log_audit('USER_GENERIC_GROUP_TYPE', code, 'CREATE', request.user.username)
                messages.success(request, '✅ Group Type added successfully!')
                return redirect('wastage:group_type_list')
            except Exception as e:
                messages.error(request, f'❌ Error: {e}')
    return render(request, 'wastage/group_type_form.html', {'title': 'Add Group Type', 'record': None})


@login_required
@page_permission_required('group_types', action='edit')
def group_type_edit(request, group_code):
    record = fetch_group_type_by_id(group_code)
    if not record:
        return redirect('wastage:group_type_list')
    if request.method == 'POST':
        try:
            old_data = {'SHORT_DESC': record['SHORT_DESC']}
            new_data = {'SHORT_DESC': request.POST.get('short_desc', '')}
            update_group_type(group_code, request.POST.get('short_desc', ''), username=request.user.username)
            log_audit('USER_GENERIC_GROUP_TYPE', group_code, 'UPDATE', request.user.username, old_data, new_data)
            messages.success(request, '✅ Group Type updated!')
            return redirect('wastage:group_type_list')
        except Exception as e:
            messages.error(request, f'❌ Error: {e}')
    return render(request, 'wastage/group_type_form.html', {'title': 'Edit Group Type', 'record': record})

@login_required
@page_permission_required('group_types', action='delete')
def group_type_delete(request, group_code):
    if request.method == 'POST':
        try:
            record = fetch_group_type_by_id(group_code)
            delete_group_type(group_code, username=request.user.username)
            log_audit('USER_GENERIC_GROUP_TYPE', group_code, 'DELETE', request.user.username, record)
            messages.success(request, '✅ Group Type deleted!')
        except Exception as e:
            messages.error(request, f'❌ Error: {e}')
    return redirect('wastage:group_type_list')


# ─── USER GENERIC GROUP ───────────────────────────────────
@login_required
@page_permission_required('group_type_values', action='view')
def generic_group_list(request):
    return render(request, 'wastage/generic_group_list.html', {'records': fetch_all_generic_groups()})

@login_required
@page_permission_required('group_type_values', action='create')
def generic_group_add(request):
    group_types = fetch_all_group_types()
    preselected = request.GET.get('group_code', '')
    if request.method == 'POST':
        code = request.POST.get('code', '').strip().upper()
        if not code:
            messages.error(request, '❌ Code is required.')
        elif check_duplicate('wst_djn_user_generic_group', 'CODE', code):
            messages.error(request, f'❌ Code "{code}" already exists.')
        else:
            try:
                insert_generic_group(code, request.POST['group_code'], request.POST.get('description', ''))
                log_audit('USER_GENERIC_GROUP', code, 'CREATE', request.user.username)
                messages.success(request, '✅ Generic Group added successfully!')
                return redirect('wastage:group_type_list')
            except Exception as e:
                messages.error(request, f'❌ Error: {e}')
    return render(request, 'wastage/generic_group_form.html', {
        'title': 'Add Detail', 'record': None,
        'group_types': group_types, 'preselected': preselected
    })

@login_required
@page_permission_required('group_type_values', action='edit')
def generic_group_edit(request, code):
    record = fetch_generic_group_by_id(code)
    group_types = fetch_all_group_types()
    if not record:
        return redirect('wastage:generic_group_list')
    if request.method == 'POST':
        try:
            old_data = {'GROUP_CODE': record['GROUP_CODE'], 'DESCRIPTION': record['DESCRIPTION']}
            new_data = {'GROUP_CODE': request.POST['group_code'], 'DESCRIPTION': request.POST.get('description', '')}
            update_generic_group(code, request.POST['group_code'], request.POST.get('description', ''))
            log_audit('USER_GENERIC_GROUP', code, 'UPDATE', request.user.username, old_data, new_data)
            messages.success(request, '✅ Generic Group updated!')
            return redirect('wastage:group_type_list')
        except Exception as e:
            messages.error(request, f'❌ Error: {e}')
    return render(request, 'wastage/generic_group_form.html', {
        'title': 'Edit Generic Group', 'record': record, 'group_types': group_types
    })

@login_required
@page_permission_required('group_type_values', action='delete')
def generic_group_delete(request, code):
    if request.method == 'POST':
        try:
            record = fetch_generic_group_by_id(code)
            delete_generic_group(code)
            log_audit('USER_GENERIC_GROUP', code, 'DELETE', request.user.username, record)
            messages.success(request, '✅ Generic Group deleted!')
        except Exception as e:
            messages.error(request, f'❌ Error: {e}')
    return redirect('wastage:group_type_list')


@login_required
@page_permission_required('group_type_values', action='create')
def generic_group_add(request):
    group_types = fetch_all_group_types()
    preselected = request.GET.get('group_code', '')
    if request.method == 'POST':
        try:
            insert_generic_group(
                request.POST['code'],
                request.POST['group_code'],
                request.POST.get('description', '')
            )
            messages.success(request, '✅ Generic Group added successfully!')
            return redirect('wastage:group_type_list')
        except Exception as e:
            messages.error(request, f'❌ Error: {e}')
    return render(request, 'wastage/generic_group_form.html', {
        'title': 'Add Detail',
        'record': None,
        'group_types': group_types,
        'preselected': preselected
    })


@login_required
@page_permission_required('audit_log', action='view')
def audit_log(request):
    table_filter = request.GET.get('table', '')
    logs = fetch_audit_logs(table_name=table_filter if table_filter else None)
    tables = [
        'CATEGORIES', 'DEPARTMENTS', 'VENDORS', 'ITEMS',
        'MONTHLY_STOCK_LIST', 'STOCK_LEDGER', 'QUOTATIONS',
        'VENDOR_ASSIGNMENT', 'STOCK_RECEIVING', 'SALES',
        'USER_GENERIC_GROUP_TYPE', 'USER_GENERIC_GROUP'
    ]
    return render(request, 'wastage/audit_log.html', {
        'logs': logs, 'tables': tables, 'selected_table': table_filter
    })




# ═══════════════════════════════════════════════════════════════════════
# STOCK LEDGER VIEW (read-only, auto-generated, month-wise, division-filtered)
# ═══════════════════════════════════════════════════════════════════════

@login_required
@page_permission_required('stock_ledger', action='view')
def ledger_view(request):
    """Stock Ledger screen — read-only, filtered by current month + user division
    (or all divisions if the user has sees_all_divisions)."""
    from datetime import datetime
    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    if sees_all:
        division_filter = request.GET.get('division', 'ALL')
        division = None if division_filter == 'ALL' else division_filter
    else:
        division_filter = user_division
        division = user_division
    now = datetime.now()
    month = request.GET.get('month', str(now.month))
    year = request.GET.get('year', str(now.year))
    item_id = request.GET.get('item_id', '')
    txn_type = request.GET.get('txn_type', 'ALL')

    records = fetch_ledger_view(division, month=month, year=year,
                                item_id=item_id if item_id else None,
                                txn_type=txn_type if txn_type != 'ALL' else None)
    items = fetch_ledger_items(division)

    # Build month options (last 12 months)
    import calendar
    month_options = []
    for i in range(12):
        m = now.month - i
        y = now.year
        if m <= 0:
            m += 12; y -= 1
        month_options.append({'month': m, 'year': y,
                              'label': f"{calendar.month_abbr[m]} {y}",
                              'selected': str(m) == str(month) and str(y) == str(year)})

    return render(request, 'wastage/ledger_view.html', {
        'records': records, 'items': items, 'month_options': month_options,
        'selected_month': month, 'selected_year': year,
        'selected_item': item_id, 'selected_type': txn_type,
        'division': user_division,
        'sees_all_divisions': sees_all,
        'division_choices': _DIVISION_CHOICES,
        'division_filter': division_filter,
    })


@login_required
@page_permission_required('stock_ledger', action='view')
def stock_ledger_pdf(request):
    """Month-wise Stock Ledger PDF. Takes the SAME filters as ledger_view
    (division / month / year / item_id / txn_type), so the export always
    matches what is on screen. Month defaults to the current month."""
    from datetime import datetime
    import calendar
    from .pdf_reports import build_ledger_pdf
    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    if sees_all:
        division_filter = request.GET.get('division', 'ALL')
        division = None if division_filter == 'ALL' else division_filter
    else:
        division_filter = user_division
        division = user_division

    now = datetime.now()
    month = request.GET.get('month', str(now.month))
    year = request.GET.get('year', str(now.year))
    # Also accept a combined "M-YYYY" period, like Stock Receiving uses.
    period = request.GET.get('period', '')
    if period and '-' in period:
        month, year = period.split('-', 1)
    try:
        month_i, year_i = int(month), int(year)
        if not 1 <= month_i <= 12:
            raise ValueError
    except (TypeError, ValueError):
        month_i, year_i = now.month, now.year
    month, year = str(month_i), str(year_i)

    item_id = request.GET.get('item_id', '').strip()
    txn_type = request.GET.get('txn_type', 'ALL').strip()
    txn_type = '' if txn_type in ('', 'ALL') else txn_type

    item_label = None
    if item_id:
        try:
            for i in fetch_ledger_items(division):
                if str(i.get('ITEM_ID')) == item_id:
                    item_label = i.get('ITEM_NAME') or item_id
                    break
        except Exception:
            pass
        item_label = item_label or item_id

    division_label = 'All Divisions' if division_filter == 'ALL' else (
        dict(_DIVISION_CHOICES).get(division_filter, division_filter))
    month_label = f'{calendar.month_name[month_i]} {year_i}'

    pdf_bytes = build_ledger_pdf(
        division_label, month_label, division, month, year,
        item_id=item_id or None, item_label=item_label, txn_type=txn_type or None,
        show_division=sees_all, generated_by=request.user.get_full_name() or request.user.username,
    )
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="stock_ledger_{year}_{month_i:02d}.pdf"'
    return response


# ═══════════════════════════════════════════════════════════════════════
# ITEM BALANCE SHEET (live position, division-filtered)
# ═══════════════════════════════════════════════════════════════════════

@login_required
@page_permission_required('item_balance', action='view')
def balance_sheet(request):
    """Item Balance Sheet — live stock position per item, filtered by user division
    (or all divisions if the user has sees_all_divisions)."""
    import csv
    from django.http import HttpResponse
    from datetime import datetime

    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    if sees_all:
        division_filter = request.GET.get('division', 'ALL')
        division = None if division_filter == 'ALL' else division_filter
        div_label = 'All Divisions' if division is None else f'Division {division}'
    else:
        division_filter = user_division
        division = user_division
        div_label = f'Division {division}'

    # CSV export
    if request.GET.get('export') == 'csv':
        rows = fetch_balance_csv_data(division)
        response = HttpResponse(content_type='text/csv')
        fname_div = division or 'ALL'
        response['Content-Disposition'] = f'attachment; filename="item_balance_{fname_div}_{datetime.now():%Y%m%d}.csv"'
        writer = csv.writer(response)
        writer.writerow(['Item Code', 'Description', 'Unit', 'Total In', 'Total Out', 'Balance', 'Status', 'Last Movement'])
        for r in rows:
            writer.writerow([
                f"WI-{r.get('ITEM_CODE','')}", r.get('ITEM_NAME',''), r.get('UNIT',''),
                r.get('TOTAL_IN',0), r.get('TOTAL_OUT',0), r.get('BALANCE',0),
                r.get('STATUS',''), r.get('LAST_MOVEMENT','')
            ])
        return response

    records = fetch_item_balance_sheet(division)
    return render(request, 'wastage/balance_sheet.html', {
        'records': records, 'division': user_division, 'div_label': div_label,
        'now': datetime.now(),
        'sees_all_divisions': sees_all,
        'division_filter': division_filter,
        'division_choices': _DIVISION_CHOICES,
    })


@login_required
@page_permission_required('stock_balance_report', action='view')
def stock_balance_report(request):
    """Historical Stock Balance Report: shows the date-picker on first load,
    and — once a Transaction Date is submitted — renders the full report
    (header metadata + item grid) in the SAME response rather than
    redirecting, so the URL never changes (same pattern already used for
    Sales' Add Detail flow)."""
    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    as_of_date = request.GET.get('as_of_date', '').strip()

    if sees_all:
        division_filter = request.GET.get('division', 'ALL')
        division = None if division_filter == 'ALL' else division_filter
    else:
        division_filter = user_division
        division = user_division

    context = {
        'sees_all_divisions': sees_all,
        'division': user_division,
        'division_choices': _DIVISION_CHOICES,
        'division_filter': division_filter,
        'as_of_date': as_of_date,
    }

    if as_of_date:
        try:
            from datetime import datetime as dt_cls
            report_meta = log_stock_balance_report(as_of_date, division, username=request.user.username)
            rows = fetch_historical_stock_balance(as_of_date, division=division)
            dt = dt_cls.strptime(as_of_date, '%Y-%m-%d')
            context.update({
                'report_generated': True,
                'doc_no': report_meta['DOC_NO'],
                'created_date': report_meta['CREATED_DATE'],
                'created_by': request.user.get_full_name() or request.user.username,
                'month_display': dt.strftime('%B %Y'),
                'as_of_date_display': dt.strftime('%d-%b-%Y'),
                'rows': rows,
            })
        except Exception as e:
            messages.error(request, f'❌ Error generating report: {e}')

    return render(request, 'wastage/stock_balance_report.html', context)


@login_required
@page_permission_required('monthly_stock_report', action='view')
def monthly_stock_report(request):
    """Monthly Stock Report: shows the Division/Month picker on first
    load, and — once a month is submitted — renders the full report in
    the SAME response, same pattern as stock_balance_report() above.
    Section totals (one per Department column, plus Opening/Adjust/
    Sale Out/Closing) are computed here from the already-fetched rows --
    no separate query, this is pure aggregation over what
    fetch_monthly_stock_report() already returned."""
    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    target_month = request.GET.get('target_month', '').strip()

    if sees_all:
        division_filter = request.GET.get('division', 'ALL')
        division = None if division_filter == 'ALL' else division_filter
    else:
        division_filter = user_division
        division = user_division

    context = {
        'sees_all_divisions': sees_all,
        'division': user_division,
        'division_choices': _DIVISION_CHOICES,
        'division_filter': division_filter,
        'target_month': target_month,
    }

    if target_month:
        try:
            from datetime import datetime as dt_cls
            report_meta = log_monthly_stock_report(division, target_month, username=request.user.username)
            rows, dept_columns = fetch_monthly_stock_report(division, target_month)
            dt = dt_cls.strptime(target_month[:7], '%Y-%m')

            dept_totals = {d['DEPT_ID']: sum(r['RECEIVED'].get(d['DEPT_ID'], 0.0) for r in rows) for d in dept_columns}
            totals = {
                'OPENING': sum(r['OPENING'] for r in rows),
                'ADJUST': sum(r['ADJUST'] for r in rows),
                'SALE_OUT': sum(r['SALE_OUT'] for r in rows),
                'CLOSING': sum(r['CLOSING'] for r in rows),
            }
            # Django templates can't index a dict by a variable key
            # (r.RECEIVED.dept_id doesn't work the way it would in
            # Python) -- so for the template specifically, RECEIVED is
            # flattened into a plain list, in the SAME order as
            # dept_columns, which a template can iterate directly with
            # a normal {% for %}. oracle_data.py's own dict-based
            # return is untouched -- the PDF export below still uses
            # it directly, since that's plain Python, not a template.
            for r in rows:
                r['RECEIVED_LIST'] = [r['RECEIVED'].get(d['DEPT_ID'], 0.0) for d in dept_columns]
            dept_totals_combined = [
                {'DEPT_NAME': d['DEPT_NAME'], 'TOTAL': dept_totals[d['DEPT_ID']]} for d in dept_columns
            ]

            context.update({
                'report_generated': True,
                'doc_no': report_meta['DOC_NO'],
                'created_date': report_meta['CREATED_DATE'],
                'created_by': request.user.get_full_name() or request.user.username,
                'month_display': dt.strftime('%B %Y'),
                'rows': rows,
                'dept_columns': dept_columns,
                'dept_totals_combined': dept_totals_combined,
                'totals': totals,
            })
        except Exception as e:
            messages.error(request, f'❌ Error generating report: {e}')

    return render(request, 'wastage/monthly_stock_report.html', context)


@login_required
@page_permission_required('monthly_stock_report', action='view')
def monthly_stock_report_pdf(request):
    """Exports the same report as a PDF, using the SAME query params the
    on-screen report was generated with, same pattern as
    stock_balance_report_pdf() above."""
    from datetime import datetime as dt_cls
    from io import BytesIO
    from django.http import HttpResponse
    from reportlab.lib.pagesizes import landscape, A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    target_month = request.GET.get('target_month', '').strip()
    doc_no = request.GET.get('doc_no', '').strip()
    created_date = request.GET.get('created_date', '').strip()

    if not target_month:
        messages.error(request, '❌ Please generate a report before exporting.')
        return redirect('wastage:monthly_stock_report')

    if sees_all:
        division_filter = request.GET.get('division', 'ALL')
        division = None if division_filter == 'ALL' else division_filter
        div_label = 'All Divisions' if division is None else f'Division {division}'
    else:
        division = user_division
        div_label = f'Division {division}'

    rows, dept_columns = fetch_monthly_stock_report(division, target_month)
    dt = dt_cls.strptime(target_month[:7], '%Y-%m')
    month_display = dt.strftime('%B %Y')
    created_by = request.user.get_full_name() or request.user.username

    dept_totals = {d['DEPT_ID']: sum(r['RECEIVED'].get(d['DEPT_ID'], 0.0) for r in rows) for d in dept_columns}
    totals = {
        'OPENING': sum(r['OPENING'] for r in rows),
        'ADJUST': sum(r['ADJUST'] for r in rows),
        'SALE_OUT': sum(r['SALE_OUT'] for r in rows),
        'CLOSING': sum(r['CLOSING'] for r in rows),
    }

    def _n(v):
        return f'{v:,.2f}' if v else '—' if v == 0 else f'{v:,.2f}'

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4),
                             topMargin=10 * mm, bottomMargin=10 * mm,
                             leftMargin=8 * mm, rightMargin=8 * mm,
                             title='Monthly Stock Report')
    styles = getSampleStyleSheet()
    story = [Paragraph("Monthly Stock Report", styles['Title']), Spacer(1, 10)]

    meta_data = [
        ['Document No:', doc_no or '—', 'Month:', month_display],
        ['Created By:', created_by, 'Creation Date/Time:', created_date or '—'],
        ['Division:', div_label, 'Items:', str(len(rows))],
    ]
    meta_table = Table(meta_data, colWidths=[35 * mm, 50 * mm, 35 * mm, 50 * mm])
    meta_table.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#334155')),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 8))

    n_dept = len(dept_columns)
    # Column widths computed from the actual page budget, not a fixed
    # per-department guess -- with a real department count in the high
    # teens, a hardcoded 16mm each ran the table's total width well
    # past what a landscape page actually has (that's exactly what
    # produced the previous version's overflow). Fixed columns take a
    # set width each; departments split whatever's left, so the total
    # always equals the page budget by construction, regardless of how
    # many departments there are.
    page_budget = (landscape(A4)[0]) - 16 * mm  # matches leftMargin+rightMargin=8mm each, set on doc below
    fixed_widths = {'desc': 30 * mm, 'unit': 9 * mm, 'opening': 13 * mm, 'adjust': 13 * mm, 'sale_out': 13 * mm, 'closing': 13 * mm}
    fixed_total = sum(fixed_widths.values())
    remaining = page_budget - fixed_total
    dept_col_width = (remaining / n_dept) if n_dept else 0

    # Font size follows from how narrow that leaves each department
    # column -- legible at each step, never fixed regardless of count.
    if dept_col_width >= 14 * mm:
        body_size = 6.5
    elif dept_col_width >= 10 * mm:
        body_size = 5.5
    elif dept_col_width >= 7 * mm:
        body_size = 4.5
    else:
        body_size = 4.0

    cell_style = ParagraphStyle('MsrCell', parent=styles['Normal'], fontSize=body_size, leading=body_size + 1)
    head_style = ParagraphStyle('MsrHead', parent=styles['Normal'], fontSize=body_size, leading=body_size + 1,
                                fontName='Helvetica-Bold', alignment=TA_CENTER, textColor=colors.white)

    headers = ['Description', 'Unit', 'Prev Mon Bal'] + [d['DEPT_SHORT_NAME'] for d in dept_columns] + ['Adjust', 'Sale Out', 'Closing']
    table_data = [[Paragraph(h, head_style) for h in headers]]
    for r in rows:
        row = [Paragraph(r['ITEM_NAME'] or '—', cell_style), r['UOM'] or '—', _n(r['OPENING'])]
        for d in dept_columns:
            row.append(_n(r['RECEIVED'].get(d['DEPT_ID'], 0.0)))
        row.extend([_n(r['ADJUST']), _n(r['SALE_OUT']), _n(r['CLOSING'])])
        table_data.append(row)
    if not rows:
        table_data.append(['No stock activity this month'] + [''] * (len(headers) - 1))

    # TOTAL row: sits directly under the last item row, inside the same
    # table, so every total lines up beneath its own column (Opening, each
    # Department, Adjust, Sale Out, Closing). Replaces the old separate
    # "Section Totals" page.
    total_row_idx = None
    if rows:
        total_row_idx = len(table_data)
        table_data.append(
            ['TOTAL', '', _n(totals['OPENING'])]
            + [_n(dept_totals[d['DEPT_ID']]) for d in dept_columns]
            + [_n(totals['ADJUST']), _n(totals['SALE_OUT']), _n(totals['CLOSING'])]
        )

    col_widths = ([fixed_widths['desc'], fixed_widths['unit'], fixed_widths['opening']]
                  + [dept_col_width] * n_dept
                  + [fixed_widths['adjust'], fixed_widths['sale_out'], fixed_widths['closing']])
    item_table = Table(table_data, colWidths=col_widths, repeatRows=1)
    item_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#10B981')),
        ('FONTSIZE', (0, 1), (-1, -1), body_size),
        ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#E5E7EB')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
    ]))
    if total_row_idx is not None:
        item_table.setStyle(TableStyle([
            ('FONTNAME', (0, total_row_idx), (-1, total_row_idx), 'Helvetica-Bold'),
            ('BACKGROUND', (0, total_row_idx), (-1, total_row_idx), colors.HexColor('#ECFDF5')),
            ('LINEABOVE', (0, total_row_idx), (-1, total_row_idx), 1, colors.HexColor('#047857')),
            ('TEXTCOLOR', (0, total_row_idx), (-1, total_row_idx), colors.HexColor('#047857')),
        ]))
    story.append(item_table)
    doc.build(story)
    buffer.seek(0)
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    fname = doc_no or f'monthly_stock_report_{target_month[:7]}'
    response['Content-Disposition'] = f'attachment; filename="{fname}.pdf"'
    return response


@login_required
@page_permission_required('stock_balance_report', action='view')
def stock_balance_report_pdf(request):
    """Exports the same report as a PDF, using the SAME query params the
    on-screen report was generated with (as_of_date, division, doc_no,
    created_date carried through as query params so the PDF's header
    matches exactly what the user saw on screen, not a freshly re-logged
    report instance)."""
    from datetime import datetime as dt_cls
    from io import BytesIO
    from django.http import HttpResponse
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    sees_all = getattr(request.user, 'sees_all_divisions', False)
    user_division = getattr(request.user, 'division', '08')
    as_of_date = request.GET.get('as_of_date', '').strip()
    doc_no = request.GET.get('doc_no', '').strip()
    created_date = request.GET.get('created_date', '').strip()

    if not as_of_date:
        messages.error(request, '❌ Please generate a report before exporting.')
        return redirect('wastage:stock_balance_report')

    if sees_all:
        division_filter = request.GET.get('division', 'ALL')
        division = None if division_filter == 'ALL' else division_filter
        div_label = 'All Divisions' if division is None else f'Division {division}'
    else:
        division = user_division
        div_label = f'Division {division}'

    rows = fetch_historical_stock_balance(as_of_date, division=division)
    dt = dt_cls.strptime(as_of_date, '%Y-%m-%d')
    month_display = dt.strftime('%B %Y')
    as_of_date_display = dt.strftime('%d-%b-%Y')
    created_by = request.user.get_full_name() or request.user.username

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter,
                             topMargin=0.6 * inch, bottomMargin=0.6 * inch,
                             leftMargin=0.6 * inch, rightMargin=0.6 * inch)
    styles = getSampleStyleSheet()
    story = [Paragraph("Historical Stock Balance Report", styles['Title']), Spacer(1, 14)]

    meta_data = [
        ['Document No:', doc_no or '—', 'Month:', month_display],
        ['Created By:', created_by, 'Creation Date/Time:', created_date or '—'],
        ['Transaction Date (As of):', as_of_date_display, 'Division:', div_label],
    ]
    meta_table = Table(meta_data, colWidths=[1.7 * inch, 1.9 * inch, 1.5 * inch, 1.9 * inch])
    meta_table.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#334155')),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 18))

    table_data = [['Item Code', 'Item Description', 'UOM', 'Stock Balance']]
    for r in rows:
        table_data.append([
            r['ITEM_CODE'], r['ITEM_NAME'] or '—', r['UNIT'] or '—',
            f"{(r['BALANCE'] or 0):.2f}"
        ])
    if not rows:
        table_data.append(['—', 'No stock activity as of this date', '—', '—'])

    item_table = Table(table_data, colWidths=[1.0 * inch, 3.3 * inch, 0.8 * inch, 1.4 * inch], repeatRows=1)
    item_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#10B981')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (3, 0), (3, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E5E7EB')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
    ]))
    story.append(item_table)
    doc.build(story)
    buffer.seek(0)

    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    fname = doc_no or f'stock_balance_{as_of_date}'
    response['Content-Disposition'] = f'attachment; filename="{fname}.pdf"'
    return response
