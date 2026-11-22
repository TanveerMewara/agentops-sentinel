# AgentOps Sentinel API + worker image (the dashboard deploys separately to Vercel).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml requirements.txt ./
COPY src ./src
COPY scripts/bootstrap_hosted.py ./scripts/bootstrap_hosted.py
RUN pip install --upgrade pip && pip install .

RUN useradd --create-home --uid 10001 sentinel
USER sentinel

ENV PORT=8000
EXPOSE 8000

# --proxy-headers lets the API see the original https scheme behind the host's
# load balancer, so session cookies are issued with the Secure flag.
CMD ["sh", "-c", "uvicorn sentinel.asgi:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
