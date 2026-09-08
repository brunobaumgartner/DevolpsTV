FROM python:3.12-slim

WORKDIR /app

RUN useradd --create-home --shell /bin/bash appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
# frontend/ é montado via volume no docker-compose.yml (não faz parte da imagem)

USER appuser

EXPOSE 7678

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7678"]
