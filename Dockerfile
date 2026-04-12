FROM python:3.11-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.9.22 /uv /uvx /bin/

COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

COPY app ./app
COPY abs_challenges.csv pitches.csv players.csv README.md ./
RUN mkdir -p /data /app/reports

ENV APP_DB_PATH=/data/abs_insights.db
ENV REPORTS_DIR=/app/reports

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
