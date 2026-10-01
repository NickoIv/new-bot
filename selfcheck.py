#!/usr/bin/env python3
"""Офлайн-самопроверка бота: запускается без сети, токена и Telegram.

    python selfcheck.py

Что проверяется:
  1. Целостность данных — у каждой страны/города есть все разделы, кураторские
     подборки и маршруты ссылаются на существующие города, подписи кнопок не
     конфликтуют между собой.
  2. HTML-безопасность — ни один текст, уходящий с parse_mode="HTML", не
     содержит незакрытых/неподдерживаемых тегов. Отдельно прогоняется
     «враждебный» вариант новости с <script> и амперсандами: раньше такой
     заголовок из RSS ломал отправку всего дайджеста.
  3. UI-прогон — весь бот кликается фейковым Telegram'ом: все страны, все
     города, все кнопки. Ловится молчание бота (нажатие без ответа) и
     исключения в обработчиках.

Код выхода 0 — всё чисто, 1 — есть проблемы.
"""
import asyncio
import os
import re
import sys
import traceback

os.environ.setdefault("BOT_TOKEN", "123456:FAKE-FOR-SELFCHECK")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    import bot
except ImportError as e:  # pragma: no cover
    print(f"❌ Не удалось импортировать bot.py: {e}")
    print("   Установи зависимости:  pip install -r requirements.txt")
    raise SystemExit(1) from None

from telegram import ReplyKeyboardMarkup  # noqa: E402

problems: list[str] = []


def fail(msg: str) -> None:
    problems.append(msg)


def go_offline() -> None:
    """Заглушки вместо всего, что ходит в сеть: и погода, и отели, и перевод,
    и курс валют. Иначе самопроверка зависела бы от интернета и от того,
    отвечает ли сегодня чужой бесплатный API."""
    bot.get_weather_one = lambda name, lat, lon: f"☀️ {name}: <b>30°C</b>"
    bot.get_city_photo = lambda city: None
    bot._resolve_page_photos = lambda page, city_en: None
    bot._fetch_osm_poi = lambda kind, lat, lon: []
    bot._search_nominatim_hotels = lambda query, lat, lon: []
    bot._fetch_overpass_hotel_pool = lambda code, ck, lat, lon: []
    bot.translate_to_russian = lambda t: t
    bot._fetch_usd_rates = lambda: {"kzt": 520.0, "usd": 1.0, "eur": 0.92, "vnd": 25400.0,
                                    "idr": 16000.0, "sgd": 1.34, "cny": 7.2, "egp": 48.0}
    bot.fetch_news = lambda limit=bot.MAX_NEWS, country=None: [{
        "hash": "h1", "title": "Заголовок & <co>", "link": "https://e.com/1?a=1&b=2",
        "summary": "Анонс & текст", "source": "Источник", "flag": "🇻🇳", "published": "01.01.2026",
    }]
    bot.search_hotels = lambda code, ck, q: [
        {"name": f"{q} Grand Hotel", "stars": 4, "area": "Center", "tag_count": 9}]

    store = {"subscribers": [], "sent_hashes": []}
    bot.load_data = lambda: {k: list(v) for k, v in store.items()}

    def _save(data):
        store.clear()
        store.update({k: list(v) for k, v in data.items()})
    bot.save_data = _save
    bot._upstash_cmd = lambda *a: None
    bot._nav_state.clear()


# ═════════════════════════════════════════════════════════════════════════════
# 1. Целостность данных
# ═════════════════════════════════════════════════════════════════════════════

def check_data() -> None:
    tables = [
        ("CITIES", bot.CITIES), ("VISA_INFO", bot.VISA_INFO),
        ("TRANSPORT_INFO_DATA", bot.TRANSPORT_INFO_DATA), ("MONEY_INFO_DATA", bot.MONEY_INFO_DATA),
        ("SAFETY_INFO_DATA", bot.SAFETY_INFO_DATA), ("SEASON_INFO_DATA", bot.SEASON_INFO_DATA),
        ("BUDGET_INFO_DATA", bot.BUDGET_INFO_DATA), ("PHRASEBOOK_DATA", bot.PHRASEBOOK_DATA),
        ("ESIM_LINKS", bot.ESIM_LINKS), ("TIMEZONES", bot.TIMEZONES),
    ]
    for code in bot.COUNTRIES:
        for name, table in tables:
            if not table.get(code):
                fail(f"страна {code}: нет данных в {name}")

    for code, cities in bot.CITIES.items():
        for c in cities:
            key = (code, c["key"])
            if key not in bot.CURATED:
                fail(f"нет кураторской подборки для города {code}/{c['key']}")
                continue
            data = bot.CURATED[key]
            for field in ("hotels", "attractions", "cafes"):
                if not data.get(field):
                    fail(f"{code}/{c['key']}: пустой раздел {field}")
            for h in data.get("hotels", []):
                if not h.get("name") or not h.get("area"):
                    fail(f"{code}/{c['key']}: отель без названия или района — {h}")
                if "stars" in h and not isinstance(h["stars"], int):
                    fail(f"{code}/{c['key']}: у отеля {h.get('name')} звёзды не целое число")
            for a in data.get("attractions", []):
                if a.get("cat") not in bot.CURATED_CAT_META:
                    fail(f"{code}/{c['key']}: достопримечательность {a.get('name')!r} с неизвестной категорией")
            for cf in data.get("cafes", []):
                if cf.get("type") not in bot.CURATED_CAFE_TYPE_META:
                    fail(f"{code}/{c['key']}: кафе {cf.get('name')!r} с неизвестным типом")

    for key in bot.ITINERARY_DATA:
        if key not in bot.CURATED:
            fail(f"маршрут для {key} не опирается на кураторские данные")
        if not bot.find_city(*key):
            fail(f"маршрут для {key} ссылается на несуществующий город")

    for name, table in (("COUNTRY_LABEL_TO_CODE", bot.COUNTRY_LABEL_TO_CODE),
                        ("CURRENCY_LABEL_TO_CODE", bot.CURRENCY_LABEL_TO_CODE)):
        labels = list(table)
        if len(labels) != len(set(labels)):
            fail(f"{name}: одинаковые подписи кнопок — часть стран/валют недостижима")

    labels = [f"{c['icon']} {c['name']}" for cities in bot.CITIES.values() for c in cities]
    dupes = {label for label in labels if labels.count(label) > 1}
    if dupes:
        fail(f"одинаковые подписи городов в разных странах: {dupes}")


# ═════════════════════════════════════════════════════════════════════════════
# 2. HTML-безопасность
# ═════════════════════════════════════════════════════════════════════════════

ALLOWED_TAGS = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "a",
                "code", "pre", "span", "tg-spoiler", "blockquote"}
_TAG_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9-]*)((?:\s[^<>]*)?)(/?)>")


def check_html(label: str, text: str) -> None:
    stack: list[str] = []
    for m in _TAG_RE.finditer(text):
        closing, name, _, selfclose = m.group(1), m.group(2).lower(), m.group(3), m.group(4)
        if name not in ALLOWED_TAGS:
            fail(f"{label}: Telegram не умеет тег <{name}> — сообщение не отправится")
            continue
        if selfclose:
            continue
        if closing:
            if not stack or stack[-1] != name:
                fail(f"{label}: закрывающий </{name}> без пары")
            else:
                stack.pop()
        else:
            stack.append(name)
    if stack:
        fail(f"{label}: не закрыты теги {stack}")

    stripped = _TAG_RE.sub("", text)
    for m in re.finditer(r"[<>]", stripped):
        fail(f"{label}: сырой символ {stripped[m.start()]!r} вне тега — "
             f"…{stripped[max(0, m.start() - 40):m.start() + 40]}…")

    without_href = re.sub(r'href="[^"]*"', 'href="#"', text)
    for m in re.finditer(r"&(?!(amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)", without_href):
        fail(f"{label}: неэкранированный «&» — …{without_href[max(0, m.start() - 40):m.start() + 40]}…")


def check_app_wiring() -> None:
    """Собираем Application и проверяем, что все обработчики и — отдельно —
    глобальный обработчик ошибок действительно зарегистрированы."""
    from telegram.ext import CommandHandler, InlineQueryHandler, MessageHandler

    saved = bot.BOT_TOKEN
    bot.BOT_TOKEN = "123456789:AAFakeTokenForSelfcheckOnly_0123456789"
    try:
        app = bot.build_app()
    except Exception as e:
        fail(f"build_app() упал: {type(e).__name__}: {e}")
        return
    finally:
        bot.BOT_TOKEN = saved

    handlers = [h for group in app.handlers.values() for h in group]
    kinds = {type(h) for h in handlers}
    for expected in (CommandHandler, InlineQueryHandler, MessageHandler):
        if expected not in kinds:
            fail(f"в приложении нет обработчика {expected.__name__}")

    commands = {h.commands for h in handlers if isinstance(h, CommandHandler)}
    flat = {c for group in commands for c in group}
    missing = {c for c, _ in bot.BOT_COMMANDS} - flat
    if missing:
        fail(f"команды {sorted(missing)} есть в меню, но не зарегистрированы в приложении")

    # error_handlers — это словарь {callback: блокирующий_флаг}, а не список.
    if not app.error_handlers:
        fail("не зарегистрирован обработчик ошибок — пользователь не узнает о сбое")
    elif bot.on_error not in app.error_handlers:
        fail("зарегистрирован не тот обработчик ошибок")


def check_long_messages() -> None:
    """Дайджест из 8 новостей легко перебирает лимит Telegram в 4096 символов,
    и тогда «Message is too long» — сообщение не получает вообще никто."""
    limit = bot.TELEGRAM_MAX_MESSAGE_LEN
    items = [{
        "hash": f"h{i}", "title": "Очень длинный заголовок новости про перелёты и визы " * 4,
        "link": "https://example.com/news", "summary": "Подробный анонс новости. " * 20,
        "source": "Источник", "flag": "🇻🇳", "published": "01.01.2026",
    } for i in range(bot.MAX_NEWS)]
    text = bot.fmt_digest(items)
    if len(text) <= limit:
        fail("тест разбивки: тестовый дайджест не дотянул до лимита Telegram")
        return

    chunks = bot.split_message(text)
    if any(len(c) > limit for c in chunks):
        fail("split_message: часть длиннее лимита Telegram — сообщение не отправится")
    if "\n\n".join(chunks) != text:
        fail("split_message: текст при разбивке теряется или искажается")

    # и настоящая отправка через edit_long: заглушка + продолжения
    sent: list[str] = []

    class FakeMessage:
        async def edit_text(self, t, **kw):
            sent.append(t)
            return self

        async def reply_text(self, t, **kw):
            sent.append(t)
            return self

    asyncio.run(bot.edit_long(FakeMessage(), text, parse_mode="HTML"))
    if len(sent) != len(chunks):
        fail(f"edit_long: отправил {len(sent)} сообщений вместо {len(chunks)}")
    if any(len(s) > limit for s in sent):
        fail("edit_long: отправил сообщение длиннее лимита Telegram")


def check_html_safety() -> None:
    for code in bot.COUNTRIES:
        rendered = {
            "VISA_INFO": bot.VISA_INFO[code],
            "fmt_safety_info": bot.fmt_safety_info(code),
            "fmt_transport_info": bot.fmt_transport_info(code),
            "fmt_money_info": bot.fmt_money_info(code),
            "fmt_season_info": bot.fmt_season_info(code),
            "fmt_budget_info": bot.fmt_budget_info(code),
            "fmt_phrasebook": bot.fmt_phrasebook(code),
            "fmt_esim_info": bot.fmt_esim_info(code),
        }
        for name, text in rendered.items():
            check_html(f"{code}/{name}", text)

    check_html("FLIGHTS_INFO", bot.FLIGHTS_INFO)

    for code, cities in bot.CITIES.items():
        for c in cities:
            key = (code, c["key"])
            city_map = bot.fmt_city_map(c)
            check_html(f"карта {code}/{c['key']}", city_map)
            if "Google Maps" not in city_map or "OpenStreetMap" not in city_map:
                fail(f"карта {code}/{c['key']}: не сформированы обе внешние карты")
            check_html(f"маршрут {code}/{c['key']}", bot.fmt_itinerary(code, c["key"]))
            for h in bot.shuffle_city_hotels(code, c["key"]):
                check_html(f"отель {key}", bot.fmt_hotel_line(1, h, c.get("en", c["name"])))
            for kind, convert, field in (("attractions", bot._curated_attraction_to_item, "attractions"),
                                         ("cafes", bot._curated_cafe_to_item, "cafes")):
                for raw in bot.CURATED[key].get(field, []):
                    check_html(f"{kind} {key}", bot.fmt_poi_line(1, convert(raw), c.get("en", c["name"])))

    # Враждебный контент из RSS: раньше ломал отправку всего дайджеста.
    hostile = {
        "hash": "x", "title": 'A & B <script>alert(1)</script> 3<5 "q"',
        "link": 'https://example.com/1?a=1&b=2', "summary": "Fish & chips <b>bold</b> 100% < 200",
        "source": "Src & Co <b>", "flag": "🇻🇳", "published": "01.01.2026",
    }
    check_html("fmt_digest (враждебный заголовок)", bot.fmt_digest([hostile]))

    # Ссылка, вырывающаяся из href, не должна попасть в разметку.
    evil = dict(hostile, link='https://e.com/" onmouseover="x')
    rendered = bot.fmt_digest([evil])
    if "onmouseover" in rendered:
        fail("fmt_digest: ссылка из RSS вырвалась из атрибута href")
    if bot.safe_link("javascript:alert(1)") or bot.safe_link("data:text/html,x"):
        fail("safe_link пропускает опасные схемы URL")


# ═════════════════════════════════════════════════════════════════════════════
# 3. UI-прогон фейковым Telegram'ом
# ═════════════════════════════════════════════════════════════════════════════

def check_ui() -> None:
    class Msg:
        def __init__(self, sent):
            self.chat_id = 42
            self._sent = sent
            self.text = ""

        async def reply_text(self, text, **kw):
            self._sent.append(("reply", text, kw.get("reply_markup")))
            return self

        async def edit_text(self, text, **kw):
            self._sent.append(("edit", text, kw.get("reply_markup")))
            return self

    class User:
        id = 42
        first_name = "Selfcheck"

    class Chat:
        id = 42

    class FakeUpdate:
        def __init__(self, text, sent):
            self.message = Msg(sent)
            self.message.text = text
            self.effective_chat = Chat()
            self.effective_user = User()

    class FakeBot:
        def __init__(self, sent):
            self._sent = sent

        async def send_message(self, chat_id, text, **kw):
            self._sent.append(("bot_msg", text, kw.get("reply_markup")))

        async def send_photo(self, chat_id, photo=None, caption=None, **kw):
            self._sent.append(("bot_photo", caption or "", None))

    class FakeCtx:
        def __init__(self, sent):
            self.bot = FakeBot(sent)

    async def press(text: str):
        sent: list = []
        try:
            await bot.handle_text(FakeUpdate(text, sent), FakeCtx(sent))
        except Exception as e:
            fail(f"нажатие {text!r} упало: {type(e).__name__}: {e}")
            traceback.print_exc()
            return []
        if not sent:
            fail(f"нажатие {text!r} не дало никакого ответа — бот молчит")
        return sent

    def buttons(sent):
        out = []
        for _, _, kb in sent:
            if isinstance(kb, ReplyKeyboardMarkup):
                out.extend(b.text for row in kb.keyboard for b in row)
        return out

    async def run():
        city_buttons = ["🏨 Отели", "📅 Маршрут", "🏛 Достопримечательности", "☕ Кафе",
                        "📰 Новости страны", "🗺️ Виза", "✈️ Рейсы из Алматы", "📶 eSIM",
                        "🧭 Полезное туристу", "⬅️ Назад"]
        practical = ["🆘 Экстренная помощь", "🚕 Транспорт", "💵 Деньги на месте",
                     "🗓 Сезонность", "🗣️ Разговорник", "💰 Бюджет поездки", "⬅️ Назад"]

        for code, cities in bot.CITIES.items():
            flag, country_name = bot.COUNTRIES[code]
            await press(f"{flag} {country_name}")
            for c in cities:
                await press(f"{c['icon']} {c['name']}")
                for label in city_buttons:
                    await press(label)
                await press("🧭 Полезное туристу")
                for label in practical:
                    await press(label)
                await press("🏠 Главное меню")
                await press(f"{flag} {country_name}")
                await press(f"{c['icon']} {c['name']}")

                # ключевая регрессия: список отелей должен реально приходить
                sent = await press("🏨 Отели")
                body = "\n".join(t for _, t, _ in sent)
                if not any(h["name"] in body for h in bot.shuffle_city_hotels(code, c["key"])):
                    fail(f"{code}/{c['key']}: по кнопке «🏨 Отели» не пришёл список отелей")

                await press("⭐ Фильтр по звёздам")
                for label in ("⭐⭐⭐⭐⭐ 5", "⭐⭐⭐⭐ 4", "⭐⭐⭐ 3 и ниже"):
                    await press("🏨 Отели")
                    await press("⭐ Фильтр по звёздам")
                    await press(label)
                await press("🏨 Отели")
                await press("🏖 Фильтр по району")
                for label in buttons(await press("🏖 Фильтр по району")):
                    if label not in ("♻️ Сбросить фильтр", "⬅️ Назад", "🏠 Главное меню"):
                        await press(label)
                await press("🏨 Отели")
                await press("🔍 Поиск отеля")
                await press("Hilton")
                await press("⬅️ Назад")

                await press("🏛 Достопримечательности")
                await press("▶️ Ещё 10")
                await press("🔀 Показать другие 30")
                await press("☕ Кафе")
                await press("▶️ Ещё 10")

        await press("🌴 Все новости")
        await press("🔔 Рассылка новостей")
        await press("🔔 Подписаться")
        await press("📖 Показать сейчас")
        await press("🔕 Отписаться")
        await press("💱 Курс валют")
        await press("🧮 Конвертер валют")
        await press("🇺🇸 USD")
        await press("500")
        await press("не число")
        await press("🔁 Сменить валюту")
        await press("ℹ️ О боте")

        # Сообщения вне сценария и «осиротевшие» кнопки после перезапуска бота.
        await press("привет, а что ты умеешь?")
        await press("📰 Новости страны")
        await press("🏨 Отели")
        await press("⬅️ Назад")

    asyncio.run(run())


# ═════════════════════════════════════════════════════════════════════════════

def main() -> int:
    go_offline()
    groups = [
        ("Целостность данных", check_data),
        ("Сборка приложения и регистрация обработчиков", check_app_wiring),
        ("HTML-безопасность сообщений", check_html_safety),
        ("Разбивка длинных сообщений", check_long_messages),
        ("Прогон интерфейса (все страны, города и кнопки)", check_ui),
    ]
    for title, fn in groups:
        before = len(problems)
        try:
            fn()
        except Exception:
            traceback.print_exc()
            fail(f"проверка «{title}» упала с исключением")
        status = "✅" if len(problems) == before else "❌"
        print(f"{status} {title}")

    print()
    if problems:
        print(f"Найдено проблем: {len(problems)}")
        for p in problems:
            print(f"  • {p}")
        return 1
    print("Все проверки пройдены ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
