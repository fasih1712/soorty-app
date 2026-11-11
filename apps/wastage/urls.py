from django.urls import path
from . import views

app_name = 'wastage'

urlpatterns = [
    # Dashboard
    path('', views.wastage_home, name='home'),

    # Categories
    path('categories/', views.category_list, name='category_list'),
    path('categories/add/', views.category_add, name='category_add'),
    path('categories/edit/<int:cat_id>/', views.category_edit, name='category_edit'),
    path('categories/delete/<int:cat_id>/', views.category_delete, name='category_delete'),

    # Departments
    path('departments/', views.department_list, name='department_list'),
    path('departments/add/', views.department_add, name='department_add'),
    path('departments/edit/<int:dept_id>/', views.department_edit, name='department_edit'),
    path('departments/delete/<int:dept_id>/', views.department_delete, name='department_delete'),

    # Vendors
    path('vendors/', views.vendor_list, name='vendor_list'),
    path('vendors/add/', views.vendor_add, name='vendor_add'),
    path('vendors/edit/<int:vendor_id>/', views.vendor_edit, name='vendor_edit'),
    path('vendors/delete/<int:vendor_id>/', views.vendor_delete, name='vendor_delete'),

    # Items
    path('items/', views.item_list, name='item_list'),
    path('items/add/', views.item_add, name='item_add'),
    path('items/edit/<int:item_id>/', views.item_edit, name='item_edit'),
    path('items/delete/<int:item_id>/', views.item_delete, name='item_delete'),

    # Monthly Stock List
    path('stock-list/', views.stock_list, name='stock_list'),
    path('stock-list/add/', views.stock_list_add, name='stock_list_add'),
    path('stock-list/edit/<int:list_id>/', views.stock_list_edit, name='stock_list_edit'),
    path('stock-list/delete/<int:list_id>/', views.stock_list_delete, name='stock_list_delete'),
    path('stock-snapshot/', views.msl_snapshot, name='msl_snapshot'),
    path('stock-snapshot/generate/', views.msl_snapshot_generate, name='msl_snapshot_generate'),
    path('stock-snapshot/<int:snapshot_id>/delete/', views.msl_snapshot_delete, name='msl_snapshot_delete'),
    path('stock-snapshot/<int:snapshot_id>/pdf/', views.msl_snapshot_pdf, name='msl_snapshot_pdf'),

    # Stock Ledger
    path('ledger/', views.ledger_list, name='ledger_list'),
    path('ledger/add/', views.ledger_add, name='ledger_add'),
    path('ledger/edit/<int:ledger_id>/', views.ledger_edit, name='ledger_edit'),
    path('ledger/delete/<int:ledger_id>/', views.ledger_delete, name='ledger_delete'),

    # Quotations
    path('quotations/', views.quotation_header_list, name='quotation_list'),
    path('quotations/pdf/', views.quotation_pdf, name='quotation_pdf'),
    path('quotations/add/', views.quotation_header_add, name='quotation_add'),
    path('quotations/comparison/', views.quotation_comparison, name='quotation_comparison'),
    path('quotations/comparison/pdf/', views.quotation_comparison_pdf, name='quotation_comparison_pdf'),
    path('quotations/comparison/select/', views.quotation_comparison_select, name='quotation_comparison_select'),
    path('quotations/comparison/lock-and-generate-sales/', views.quotation_lock_and_generate_sales, name='quotation_lock_and_generate_sales'),
    path('quotations/comparison/unlock/', views.quotation_comparison_unlock, name='quotation_comparison_unlock'),
    path('quotations/<str:doc_id>/', views.quotation_header_edit, name='quotation_header_edit'),
    path('quotations/<str:doc_id>/pdf/', views.quotation_detail_pdf, name='quotation_detail_pdf'),
    path('quotations/<str:doc_id>/lines/bulk-save/', views.quotation_lines_bulk_save, name='quotation_lines_bulk_save'),
    path('quotations/<str:doc_id>/line/<int:line_id>/delete/', views.quotation_line_delete, name='quotation_line_delete'),
    path('quotations/<str:doc_id>/line/<int:line_id>/edit-price/', views.quotation_line_edit_price, name='quotation_line_edit_price'),
    path('quotations/<str:doc_id>/delete/', views.quotation_header_delete, name='quotation_header_delete'),

    # Vendor Assignment
    path('assignments/', views.assignment_list, name='assignment_list'),
    path('assignments/add/', views.assignment_add, name='assignment_add'),
    path('assignments/edit/<int:assign_id>/', views.assignment_edit, name='assignment_edit'),
    path('assignments/delete/<int:assign_id>/', views.assignment_delete, name='assignment_delete'),

    # Stock Receiving
    path('receiving/', views.receiving_list, name='receiving_list'),
    path('receiving/pdf/', views.receiving_pdf, name='receiving_pdf'),
    path('receiving/add/', views.receiving_add, name='receiving_add'),
    path('receiving/edit/<int:receive_id>/', views.receiving_edit, name='receiving_edit'),
    path('receiving/delete/<int:receive_id>/', views.receiving_delete, name='receiving_delete'),

    # Sales
    path('sales/', views.sales_header_list, name='sales_list'),
    path('sales/pdf/', views.sales_pdf, name='sales_pdf'),
    path('sales/add/', views.sales_header_add, name='sales_add'),
    path('sales/<str:doc_id>/', views.sales_header_edit, name='sales_header_edit'),
    path('sales/<str:doc_id>/pdf/', views.sales_detail_pdf, name='sales_detail_pdf'),
    path('sales/<str:doc_id>/line/add/', views.sales_line_add, name='sales_line_add'),
    path('sales/<str:doc_id>/line/<int:line_id>/delete/', views.sales_line_delete, name='sales_line_delete'),
    path('sales/<str:doc_id>/line/<int:line_id>/edit/', views.sales_line_edit, name='sales_line_edit'),
    path('sales/<str:doc_id>/lines/bulk-save/', views.sales_lines_bulk_save, name='sales_lines_bulk_save'),
    path('sales/<str:doc_id>/post/', views.sales_header_post, name='sales_header_post'),
    path('sales/<str:doc_id>/cancel/', views.sales_header_cancel, name='sales_header_cancel'),
    path('shipments/', views.shipment_list, name='shipment_list'),
    path('shipments/<str:ship_doc_id>/cancel/', views.shipment_cancel, name='shipment_cancel'),
    path('gatepass/', views.gatepass_list, name='gatepass_list'),
    path('gatepass/pdf/', views.gatepass_pdf, name='gatepass_pdf'),
    path('gatepass/add/', views.gatepass_add, name='gatepass_add'),
    path('gatepass/add-sender/', views.gatepass_add_sender, name='gatepass_add_sender'),
    path('gatepass/<str:gate_pass_id>/edit/', views.gatepass_add, name='gatepass_edit'),
    path('gatepass/<str:gate_pass_id>/', views.gatepass_view, name='gatepass_view'),
    path('gatepass/<str:gate_pass_id>/pdf/', views.gatepass_detail_pdf, name='gatepass_detail_pdf'),
    path('gatepass/<str:gate_pass_id>/cancel/', views.gatepass_cancel, name='gatepass_cancel'),
    path('gatepass/<str:gate_pass_id>/manual-no/', views.gatepass_set_manual_no, name='gatepass_set_manual_no'),
    path('gatepass/<str:gate_pass_id>/delete/', views.gatepass_delete, name='gatepass_delete'),
    path('sales/<str:doc_id>/delete/', views.sales_header_delete, name='sales_header_delete'),

    # WhatsApp Log
    path('whatsapp/', views.whatsapp_list, name='whatsapp_list'),

    # User Generic Group Type (Master)
    path('group-types/', views.group_type_list, name='group_type_list'),
    path('group-types/add/', views.group_type_add, name='group_type_add'),
    path('group-types/edit/<str:group_code>/', views.group_type_edit, name='group_type_edit'),
    path('group-types/delete/<str:group_code>/', views.group_type_delete, name='group_type_delete'),

    # User Generic Group (Child)
    path('generic-groups/', views.generic_group_list, name='generic_group_list'),
    path('generic-groups/add/', views.generic_group_add, name='generic_group_add'),
    path('generic-groups/edit/<str:code>/', views.generic_group_edit, name='generic_group_edit'),
    path('generic-groups/delete/<str:code>/', views.generic_group_delete, name='generic_group_delete'),

    path('audit-log/', views.audit_log, name='audit_log'),

    # Stock Ledger (read-only, auto-generated)
    path('ledger-view/', views.ledger_view, name='ledger_view'),
    path('ledger-view/pdf/', views.stock_ledger_pdf, name='stock_ledger_pdf'),

    # Item Balance Sheet (live position)
    path('balance/', views.balance_sheet, name='balance_sheet'),
    path('reports/stock-balance/', views.stock_balance_report, name='stock_balance_report'),
    path('reports/stock-balance/pdf/', views.stock_balance_report_pdf, name='stock_balance_report_pdf'),
    path('reports/monthly-stock/', views.monthly_stock_report, name='monthly_stock_report'),
    path('reports/monthly-stock/pdf/', views.monthly_stock_report_pdf, name='monthly_stock_report_pdf'),
]



