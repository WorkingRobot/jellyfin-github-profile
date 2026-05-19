FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY api/requirements.txt /app/api/requirements.txt
RUN pip install --no-cache-dir -r /app/api/requirements.txt

COPY api/ /app/api/
COPY util/ /app/util/

EXPOSE 8080

# Single worker so the in-process now-playing + album-art caches are shared
# by every request; threads handle concurrency (work is I/O-bound).
CMD ["gunicorn", "-w", "1", "--threads", "16", "-k", "gthread", \
     "--timeout", "30", "-b", "0.0.0.0:8080", "api.app:app"]
