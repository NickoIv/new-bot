FROM python:3.12-slim

# Без этого логи пишутся в буфер и в панели хостинга не видны до перезапуска —
# отлаживать падения становится невозможно.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .

# Режим выбирается переменной WEBHOOK_MODE (на Render платформа выставляет
# RENDER=1 сама, локально без переменных бот работает через polling).
CMD ["python", "bot.py"]
