FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY preflight/ preflight/
COPY web/ web/

ENV PREFLIGHT_MODE=hosted PORT=8000
EXPOSE 8000
# PREFLIGHT_PASSWORD must be supplied at run time; the app refuses to start hosted without it.
CMD ["sh", "-c", "uvicorn web.app:app --host 0.0.0.0 --port ${PORT}"]
