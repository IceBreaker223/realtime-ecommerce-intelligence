FROM python:3.11-slim@sha256:da047cb8f9d1d98e5c070f5300ba9f7274e33b8fc0e5be5ed88740aed1b95ba9
WORKDIR /app
COPY requirements.txt /app/requirements.txt
COPY api/requirements*.txt /app/api/
COPY api/constraints.txt /app/api/constraints.txt
RUN pip install --no-cache-dir -r requirements.txt -r api/requirements-dev.txt
COPY producer /app/producer
COPY streaming /app/streaming
COPY detection /app/detection
COPY api /app/api
COPY tests /app/tests
COPY scripts /app/scripts
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "scripts.demo"]
