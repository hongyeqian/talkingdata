FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# Bake the deterministic business database into the image
RUN python -m rlvr_env.db_init --force

# Default: run the demo scenarios and print rewards
CMD ["python", "examples/run_demo.py"]
