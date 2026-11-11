"""
Waitress WSGI entry point for Soorty ERP on Windows Server.
Run directly for testing:  venv\Scripts\python.exe waitress_server.py
In production, NSSM runs this same command as a managed Windows Service (see install_service.ps1).
"""

import os

from waitress import serve

# Point this at your actual Django settings module
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

import django  # noqa: E402

django.setup()

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()

if __name__ == "__main__":
    serve(
        application,
        listen="127.0.0.1:8000",
        threads=8,
        channel_timeout=120,
    )
