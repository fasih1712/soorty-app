from django.urls import path

from . import views

app_name = 'finance'

urlpatterns = [
    path('', views.finance_home, name='home'),

    # Chart of accounts
    path('accounts/', views.coa_list, name='coa_list'),
    path('accounts/add/', views.coa_add, name='coa_add'),
    path('accounts/<int:account_id>/edit/', views.coa_edit, name='coa_edit'),
    path('accounts/<int:account_id>/toggle/', views.coa_toggle, name='coa_toggle'),

    # Configuration
    path('settings/', views.settings_list, name='settings'),
    path('settings/<str:key>/update/', views.setting_update, name='setting_update'),
    path('posting-rules/', views.posting_rules, name='posting_rules'),
    path('posting-rules/<int:rule_id>/update/', views.posting_rule_update, name='posting_rule_update'),

    # Periods
    path('periods/', views.periods, name='periods'),
    path('periods/lock/', views.period_lock, name='period_lock'),
    path('periods/reopen/', views.period_reopen, name='period_reopen'),

    # Phase 2 - customers, advances, vouchers, events
    path('customers/', views.customers, name='customers'),
    path('customers/<int:party_id>/', views.customer_ledger, name='customer_ledger'),
    path('advances/add/', views.advance_add, name='advance_add'),
    path('advances/opening/', views.opening_add, name='opening_add'),
    path('advances/<int:advance_id>/reverse/', views.advance_reverse, name='advance_reverse'),
    path('vouchers/', views.vouchers, name='vouchers'),
    path('vouchers/<int:voucher_id>/', views.voucher_view, name='voucher_view'),
    path('events/', views.events, name='events'),
    path('events/retry/', views.event_retry, name='event_retry'),

    # Phase 3 - adjustments
    path('adjustments/', views.adjustments, name='adjustments'),
    path('adjustments/refund/', views.adjustment_refund, name='adjustment_refund'),
    path('adjustments/note/', views.adjustment_note, name='adjustment_note'),
    path('adjustments/transfer/', views.adjustment_transfer, name='adjustment_transfer'),
    path('adjustments/journal/', views.adjustment_journal, name='adjustment_journal'),
    path('adjustments/<int:adjustment_id>/reverse/', views.adjustment_reverse, name='adjustment_reverse'),

    # Audit
    path('audit/', views.finance_audit, name='audit'),

    # Phase 4 - reports
    path('reports/', views.report_index, name='reports'),
    path('reports/advance-statement/', views.report_statement, name='report_statement'),
    path('reports/trial-balance/', views.report_trial_balance, name='report_trial_balance'),
    path('reports/general-ledger/', views.report_ledger, name='report_ledger'),
    path('reports/sales-collections/', views.report_sales, name='report_sales'),
    path('reports/reconciliation/', views.report_reconciliation, name='report_reconciliation'),
    path('reports/advance-ageing/', views.report_ageing, name='report_ageing'),
]
