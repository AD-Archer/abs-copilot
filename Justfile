set dotenv-load := true

@default:
  just --list

setup:
  uv venv .venv
  . .venv/bin/activate && uv pip install -r requirements.txt

run:
  . .venv/bin/activate && uvicorn app.main:app --reload

test:
  . .venv/bin/activate && pytest -q

lint:
  . .venv/bin/activate && python -m compileall app tests

docker-build:
  docker build -t abs-copilot .

docker-run:
  docker run --rm -p 8000:8000 --env-file .env -v "$(pwd)/reports:/app/reports" abs-copilot

smoke:
  curl -s http://localhost:8000/health

