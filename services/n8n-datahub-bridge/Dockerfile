FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir uv && uv pip install --system --no-cache .

COPY src/ src/

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "bridge.main:app", "--host", "0.0.0.0", "--port", "8000"]
