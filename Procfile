# webhook-режим (Render/Heroku web-dyno): бот поднимает HTTP-сервер на $PORT.
# Раньше здесь стоял только worker — на платформах без Docker это не даёт
# публичного адреса, и Telegram не может доставить вебхук.
web: python bot.py
# polling-режим (фоновый воркер): исходящий polling, внешний порт не нужен.
worker: python bot.py
