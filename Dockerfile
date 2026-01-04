FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml /app/pyproject.toml
COPY uv.lock /app/uv.lock
RUN uv sync --no-dev --python 3.13

COPY app /app/app

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
