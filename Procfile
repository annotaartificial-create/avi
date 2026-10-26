web: python manage.py migrate --noinput && python manage.py collectstatic --noinput && gunicorn avi.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 2 --threads 4
