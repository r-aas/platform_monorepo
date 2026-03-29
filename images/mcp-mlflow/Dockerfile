FROM python:3.12-slim

WORKDIR /app
COPY server.py .

RUN pip install --no-cache-dir "mcp[cli]>=1.9.0" httpx

EXPOSE 3000
CMD ["python", "server.py"]
