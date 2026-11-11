from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.home, name='home'),
    path('emp-form/', views.emp_form, name='emp_form'),
    path('emp-edit/<int:empno>/', views.emp_edit, name='emp_edit'),
    path('emp-delete/<int:empno>/', views.emp_delete, name='emp_delete'),
    path('emp-export-pdf/', views.export_emp_pdf, name='emp_export_pdf'),
]