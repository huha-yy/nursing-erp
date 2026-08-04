FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

RUN pip install --no-cache-dir \
    django==5.1.* \
    django-unfold>=0.40 \
    django-ninja>=1.3 \
    psycopg2-binary>=2.9 \
    django-import-export>=4.0 \
    uvicorn>=0.30 \
    gunicorn>=22 \
    whitenoise>=6

COPY . .
RUN python manage.py collectstatic --noinput

EXPOSE 8080
CMD ["gunicorn", "nursing_erp.wsgi:application", "--bind", "0.0.0.0:8080", "--workers", "2"]
