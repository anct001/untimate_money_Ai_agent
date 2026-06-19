# Container for the SaaS automation API (python -m moneyagent serve).
FROM python:3.11-slim

WORKDIR /app

# Install with the SaaS extras (FastAPI/uvicorn/stripe).
COPY pyproject.toml README.md ./
COPY moneyagent ./moneyagent
RUN pip install --no-cache-dir -e ".[saas]"

# Runtime config is provided via env / mounted .env (never bake secrets in).
EXPOSE 8000
ENV PYTHONUNBUFFERED=1

# 0.0.0.0 so the port is reachable from outside the container.
CMD ["python", "-m", "moneyagent", "serve", "--host", "0.0.0.0", "--port", "8000"]
