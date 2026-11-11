from django.contrib import admin
from django.urls import path, include
from apps.dashboard import views as dashboard_views
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('apps.accounts.urls')),
    path('dashboard/', include('apps.dashboard.urls')),
    path('wastage/', include('apps.wastage.urls')),
    path('', dashboard_views.home, name='home'),
    path('finance/', include('apps.finance.urls')),
]