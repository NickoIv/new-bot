FROM python:3.12-slim

# Без этого логи пишутся в буфер и в панели хостинга не видны до перезапуска —
# отлаживать падения становится невозможно.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Даже при уязвимости в библиотеке процесс бота не должен иметь права root.
# Каталог /app остаётся доступным для записи: локальный fallback-хранилища
# продолжит работать, если Upstash временно не настроен.
RUN addgroup --system bot \
    && adduser --system --ingroup bot --home /app --no-create-home bot \
    && chown bot:bot /app

COPY --chown=bot:bot bot.py .
USER bot

# Режим выбирается переменной WEBHOOK_MODE (на Render платформа выставляет
# RENDER=1 сама, локально без переменных бот работает через polling).
CMD ["python", "bot.py"]
