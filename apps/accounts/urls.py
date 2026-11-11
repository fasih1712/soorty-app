from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('users/', views.user_list, name='user_list'),
    path('users/create/', views.user_create, name='user_create'),
    path('users/datatex-lookup/', views.datatex_lookup, name='datatex_lookup'),
    path('users/datatex-search/', views.datatex_search, name='datatex_search'),
    path('users/edit/<int:user_id>/', views.user_edit, name='user_edit'),
    path('users/delete/<int:user_id>/', views.user_delete, name='user_delete'),
    path('roles/', views.role_list, name='role_list'),
    path('roles/create/', views.role_create, name='role_create'),
    path('roles/edit/<int:group_id>/', views.role_edit, name='role_edit'),
    path('roles/delete/<int:group_id>/', views.role_delete, name='role_delete'),
]