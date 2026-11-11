from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser

@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ['username', 'email', 'role', 'department', 'employee_id', 'division', 'sees_all_divisions', 'is_active']
    list_filter = ['role', 'department', 'division', 'sees_all_divisions', 'is_active']
    fieldsets = UserAdmin.fieldsets + (
        ('Soorty Profile', {'fields': ('role', 'department', 'employee_id', 'phone')}),
        ('Division Access', {'fields': ('division', 'sees_all_divisions')}),
    )