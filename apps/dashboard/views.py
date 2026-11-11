from django.http import HttpResponse
from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages
from .oracle_data import (
    fetch_sales_summary, fetch_recent_orders,
    fetch_employee_summary, insert_emp, fetch_all_employees,
    fetch_emp_by_id, update_emp, delete_emp
)
from .forms import EmpForm


@login_required
def home(request):
    try:
        sales = fetch_sales_summary()
        orders = fetch_recent_orders()
        emp = fetch_employee_summary()
    except Exception as e:
        sales, orders, emp = {}, [], {}
    return render(request, 'dashboard/home.html', {
        'sales': sales,
        'recent_orders': orders,
        'emp': emp,
    })


@login_required
def emp_form(request):
    form = EmpForm()
    employees = fetch_all_employees()

    if request.method == 'POST':
        form = EmpForm(request.POST)
        if form.is_valid():
            try:
                insert_emp(
                    ename    = form.cleaned_data['ename'],
                    job      = form.cleaned_data['job'],
                    mgr      = form.cleaned_data['mgr'],
                    hiredate = form.cleaned_data['hiredate'],
                    sal      = form.cleaned_data['sal'],
                    comm     = form.cleaned_data['comm'],
                    deptno   = form.cleaned_data['deptno'],
                )
                messages.success(request, f"✅ Employee '{form.cleaned_data['ename'].upper()}' added successfully!")
                return redirect('dashboard:emp_form')
            except Exception as e:
                messages.error(request, f"❌ Database error: {str(e)}")

    return render(request, 'dashboard/emp_form.html', {
        'form': form,
        'employees': employees,
    })


@login_required
def emp_edit(request, empno):
    emp = fetch_emp_by_id(empno)
    if not emp:
        messages.error(request, 'Employee not found.')
        return redirect('dashboard:emp_form')

    form = EmpForm(initial={
        'ename':    emp['ENAME'],
        'job':      emp['JOB'],
        'mgr':      emp['MGR'],
        'hiredate': emp['HIREDATE'],
        'sal':      emp['SAL'],
        'comm':     emp['COMM'],
        'deptno':   emp['DEPTNO'],
    })

    if request.method == 'POST':
        form = EmpForm(request.POST)
        if form.is_valid():
            try:
                update_emp(
                    empno    = empno,
                    ename    = form.cleaned_data['ename'],
                    job      = form.cleaned_data['job'],
                    mgr      = form.cleaned_data['mgr'],
                    hiredate = form.cleaned_data['hiredate'],
                    sal      = form.cleaned_data['sal'],
                    comm     = form.cleaned_data['comm'],
                    deptno   = form.cleaned_data['deptno'],
                )
                messages.success(request, f"✅ Employee #{empno} updated successfully!")
                return redirect('dashboard:emp_form')
            except Exception as e:
                messages.error(request, f"❌ Database error: {str(e)}")

    return render(request, 'dashboard/emp_edit.html', {
        'form': form,
        'emp': emp,
        'empno': empno,
    })


@login_required
def emp_delete(request, empno):
    if request.method == 'POST':
        try:
            delete_emp(empno)
            messages.success(request, f"✅ Employee #{empno} deleted successfully!")
        except Exception as e:
            messages.error(request, f"❌ Database error: {str(e)}")
    return redirect('dashboard:emp_form')


@login_required
def export_emp_pdf(request):
    employees = fetch_all_employees()

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="soorty_employees.pdf"'

    doc = SimpleDocTemplate(
        response,
        pagesize=landscape(A4),
        rightMargin=30, leftMargin=30,
        topMargin=30, bottomMargin=30
    )

    styles = getSampleStyleSheet()
    elements = []

    # Title
    title = Paragraph("<b>Soorty — Employee Report</b>", styles['Title'])
    elements.append(title)
    elements.append(Spacer(1, 0.2 * inch))

    # Table header
    headers = ['Emp No', 'Name', 'Job', 'Manager', 'Hire Date', 'Salary', 'Commission', 'Department', 'Location']
    data = [headers]

    # Table rows
    for emp in employees:
        data.append([
            str(emp['EMPNO'] or ''),
            str(emp['ENAME'] or ''),
            str(emp['JOB'] or ''),
            str(emp['MGR'] or ''),
            str(emp['HIREDATE'] or ''),
            f"${emp['SAL']:,.0f}" if emp['SAL'] else '',
            f"${emp['COMM']:,.0f}" if emp['COMM'] else '',
            str(emp['DNAME'] or ''),
            str(emp['LOC'] or ''),
        ])

    # Build table
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        # Header row
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a2332')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),

        # Data rows
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('ALIGN', (0, 1), (-1, -1), 'CENTER'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f6fa')]),
        ('TOPPADDING', (0, 1), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 5),

        # Grid
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#e0e0e0')),
        ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor('#1a2332')),
    ]))

    elements.append(table)
    doc.build(elements)
    return response