FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

# logs/ and media/ are mounted as volumes at runtime; create them for build + first run.
# collectstatic needs settings to import, so give it throwaway values (no DB connection is made).
RUN mkdir -p logs media staticfiles \
    && SECRET_KEY=build-only DEBUG=False ALLOWED_HOSTS=localhost \
       DB_SERVICE=x DB_USER=x DB_PASSWORD=x \
       python manage.py collectstatic --noinput \
    && useradd --create-home --uid 1000 app \
    && chown -R app:app /app

USER app

EXPOSE 8000

CMD ["gunicorn", "core.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--threads", "4", \
     "--timeout", "120", \
     "--access-logfile", "-"]
