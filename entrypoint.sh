#!/usr/bin/env bash
set -e

# Wait for DB if using DATABASE_URL with a host
if [ -n "$DATABASE_URL" ]; then
  echo "Waiting for database to be ready..."
  # Basic wait (optional: parse host/port from DATABASE_URL)
  sleep 2
fi

python manage.py migrate --noinput
python manage.py collectstatic --noinput

# Start server (use gunicorn in prod, can switch to runserver for dev)
exec gunicorn API.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers ${GUNICORN_WORKERS:-3} \
  --timeout ${GUNICORN_TIMEOUT:-120} 