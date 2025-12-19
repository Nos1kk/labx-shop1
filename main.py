import logging
import asyncio
import os
import uuid

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    WebAppInfo,
    FSInputFile,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
import aiofiles

from db import (
    init_db, add_order, get_orders, update_order, delete_order,
    add_chat_message, get_chat_history, get_all_chats, mark_chat_as_read,
    add_order_file, get_order_files
)

# === КОНФИГ ===
BOT_TOKEN = "8289409350:AAFLRXZyD-yoRU9vXW8t1HjQDJ2VVNnv9qo"
WEBAPP_URL = "https://valiantly-disarming-vireo.cloudpub.ru"
ADMIN_IDS = [5270338617]
CARD_NUMBER = "2202 2081 6267 4528"

# КНОПКА "Отзывы" (если захочешь использовать)
REVIEWS_LINK = "https://t.me/your_reviews_channel"

# ПРОМОКОДЫ — ТЕПЕРЬ ЗДЕСЬ
# ---------------------------------
#  code: {
#      "discount": скидка в %,           (int)
#      "uses_left": сколько раз можно,   (int или None = бесконечно)
# }
PROMO_CODES = {
    "LABX10":   {"discount": 10, "uses_left": None},
    "LABX20":   {"discount": 20, "uses_left": None},
    "FIRST15":  {"discount": 15, "uses_left": None},
    "NEWYEAR20": {"discount": 20, "uses_left": 500},  # пример новогоднего
}
# ---------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

if os.path.exists("/data"):
    # Мы на сервере Amvera
    STATIC_DIR = "/data/static"
    UPLOAD_DIR = "/data/uploads"
else:
    # Мы на компьютере
    STATIC_DIR = "static"
    UPLOAD_DIR = "uploads"
    
for d in (STATIC_DIR, UPLOAD_DIR):
    if not os.path.exists(d):
        os.makedirs(d)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
templates = Jinja2Templates(directory="templates")
init_db()

# активный чат для каждого админа
admin_active_chat: dict[int, int] = {}


# ========== TELEGRAM BOT ==========

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user = message.from_user
    u_name = user.username or "Guest"
    start_url = f"{WEBAPP_URL}/?uid={user.id}&user={u_name}"

    kb = ReplyKeyboardMarkup(
        resize_keyboard=True,
        keyboard=[
            [KeyboardButton(text="🛍 Открыть магазин", web_app=WebAppInfo(url=start_url))],
            [KeyboardButton(text="⭐️ Отзывы"), KeyboardButton(text="📞 Поддержка")]
        ]
    )

    text = (
        "👋 <b>Добро пожаловать в LabX!</b>\n\n"
        "🧪 Лабораторные, практики\n"
        "💻 Курсовые и приложения\n"
        "🛠 Индивидуальные задачи\n\n"
        "Нажмите кнопку ниже, чтобы открыть мини‑приложение."
    )

    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@dp.message(F.text == "⭐️ Отзывы")
async def cmd_reviews(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 Смотреть отзывы", url=REVIEWS_LINK)]
    ])
    await message.answer(
        "⭐️ <b>Отзывы о LabX</b>\n\n"
        "Мы собрали реальные отзывы студентов.\n"
        "Перейдите по кнопке ниже, чтобы посмотреть.",
        reply_markup=kb,
        parse_mode="HTML"
    )


@dp.message(F.text == "📞 Поддержка")
async def cmd_support_button(message: types.Message):
    u_name = message.from_user.username or "Guest"
    url = f"{WEBAPP_URL}/?uid={message.from_user.id}&user={u_name}"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="💬 Открыть чат", web_app=WebAppInfo(url=url + "#support"))]]
    )
    await message.answer(
        "💬 <b>Чат поддержки</b>\n\n"
        "Нажмите кнопку ниже, чтобы открыть чат прямо в мини‑приложении.",
        reply_markup=kb,
        parse_mode="HTML"
    )


@dp.message(Command("chats"))
async def cmd_chats(message: types.Message):
    """Список чатов для админа."""
    if message.from_user.id not in ADMIN_IDS:
        return

    chats = get_all_chats()
    if not chats:
        await message.answer("📭 Нет активных чатов")
        return

    buttons = []
    for chat in chats:
        unread = f"🔴{chat['unread']}" if chat['unread'] > 0 else "✅"
        username = f"@{chat['username']}" if chat['username'] else "Без username"
        text = f"{unread} {username} ({chat['user_id']})"
        buttons.append([InlineKeyboardButton(text=text, callback_data=f"chat_{chat['user_id']}")])

    await message.answer("📬 Выберите чат:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@dp.callback_query(F.data.startswith("chat_"))
async def cb_select_chat(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return

    user_id = int(callback.data.split("_")[1])
    admin_active_chat[callback.from_user.id] = user_id
    mark_chat_as_read(user_id)

    history = get_chat_history(user_id)
    txt = f"💬 <b>Чат с пользователем ID: {user_id}</b>\n\n"
    if history:
        for msg in history[-10:]:
            who = "👤" if msg["sender"] == "user" else "👨‍💼"
            t = msg["timestamp"][11:16] if msg["timestamp"] else ""
            txt += f"{who} [{t}] {msg['message'][:80]}\n"
            if msg["file_url"]:
                txt += f"   📎 {msg['file_url']}\n"
    else:
        txt += "<i>Сообщений пока нет</i>\n"

    txt += "\n✏️ Просто напишите сообщение — оно уйдёт этому пользователю."
    await callback.message.answer(txt, parse_mode="HTML")
    await callback.answer("Чат выбран")


@dp.message(Command("endchat"))
async def cmd_endchat(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    if message.from_user.id in admin_active_chat:
        del admin_active_chat[message.from_user.id]
        await message.answer("✅ Активный чат сброшен. Используйте /chats для выбора нового.")
    else:
        await message.answer("ℹ️ Активный чат не выбран.")


async def _save_admin_file(message: types.Message) -> str:
    """
    Сохранение любого вложения админа:
    фото, документ, видео, голос, аудио и т.д.
    Возвращает относительный URL ("/static/..") или "".
    """
    file_id = None
    filename = None
    ext = ".bin"

    if message.photo:
        file_id = message.photo[-1].file_id
        ext = ".jpg"
        filename = f"{uuid.uuid4().hex}{ext}"
    elif message.document:
        file_id = message.document.file_id
        original = message.document.file_name or "file"
        _, e = os.path.splitext(original)
        ext = e or ".bin"
        filename = f"{uuid.uuid4().hex}{ext}"
    elif message.video:
        file_id = message.video.file_id
        ext = ".mp4"
        filename = f"{uuid.uuid4().hex}{ext}"
    elif message.audio:
        file_id = message.audio.file_id
        ext = ".mp3"
        filename = f"{uuid.uuid4().hex}{ext}"
    elif message.voice:
        file_id = message.voice.file_id
        ext = ".ogg"
        filename = f"{uuid.uuid4().hex}{ext}"
    elif message.video_note:
        file_id = message.video_note.file_id
        ext = ".mp4"
        filename = f"{uuid.uuid4().hex}{ext}"

    if not file_id:
        return ""

    try:
        file = await bot.get_file(file_id)
        path = os.path.join(STATIC_DIR, filename)
        await bot.download_file(file.file_path, path)
        logger.info(f"Admin file saved: {path}")
        return f"/static/{filename}"
    except Exception as e:
        logger.error(f"Failed to save admin file: {e}")
        return ""


@dp.message(F.from_user.id.in_(ADMIN_IDS))
async def admin_reply(message: types.Message):
    """
    Любое текст/фото/файл от админа — как ответ пользователю в активном чате.
    Команды (/start, /chats, ...) и кнопки игнорируем.
    """
    if message.text and message.text.startswith("/"):
        return
    if message.text in ("⭐️ Отзывы", "📞 Поддержка", "🛍 Открыть магазин"):
        return

    admin_id = message.from_user.id
    if admin_id not in admin_active_chat:
        await message.answer("❓ Сначала выберите чат через /chats")
        return

    user_id = admin_active_chat[admin_id]
    text = message.text or message.caption or ""
    file_url = ""

    # сохраняем любой тип файла
    file_url = await _save_admin_file(message)

    if not text and file_url:
        text = "📎 Файл от поддержки"
    if not text:
        return

    # пишем в БД историю
    add_chat_message(user_id, "admin", text, file_url)

    # уведомляем пользователя
    try:
        await bot.send_message(
            user_id,
            "🔔 <b>Новое сообщение от поддержки</b>\n\n"
            "Откройте вкладку «Чат» в мини‑приложении, чтобы посмотреть.",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Failed to notify user {user_id}: {e}")

    await message.answer(f"✅ Сообщение отправлено пользователю (ID: {user_id})")


# ========== MINI‑APP API ==========

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


def apply_promo(code: str) -> int:
    """
    Проверка промокода в словаре PROMO_CODES.
    Возвращает скидку в % (0 если промокод не найден/исчерпан).
    Одновременно уменьшает uses_left, если он ограничен.
    """
    if not code:
        return 0

    code = code.strip().upper()
    promo = PROMO_CODES.get(code)
    if not promo:
        return 0

    uses_left = promo.get("uses_left")
    if uses_left is not None and uses_left <= 0:
        return 0

    discount = int(promo.get("discount", 0)) or 0

    # уменьшаем uses_left, если он ограничен
    if uses_left is not None:
        promo["uses_left"] = uses_left - 1
        PROMO_CODES[code] = promo

    return discount


@app.post("/api/create_order")
async def create_order_api(data: dict):
    """
    Создание заказа из корзины mini‑app.
    Здесь же применяется промокод из PROMO_CODES.
    """
    user_id = data.get("user_id")
    username = data.get("username", "")
    cart = data.get("cart", [])
    promo_code = (data.get("promo_code") or "").strip().upper()

    if not user_id or not cart:
        return {"status": "error", "message": "Пустая корзина"}

    # применяем промокод
    discount = apply_promo(promo_code)
    promo_info = ""
    if promo_code:
        if discount > 0:
            promo_info = f"\n🎟 Промокод: <b>{promo_code}</b> (-{discount}%)"
        else:
            promo_info = f"\n⚠️ Промокод <b>{promo_code}</b> недействителен"

    msg = f"🆕 <b>Новый заказ</b>\n👤 @{username} (ID: {user_id}){promo_info}\n\n"

    order_ids = []
    for item in cart:
        order_id = add_order(
            user_id,
            username,
            item.get("type", ""),
            item.get("name", ""),
            item.get("desc", ""),
            item.get("file_url", ""),
            discount
        )
        order_ids.append(order_id)
        msg += f"📦 #{order_id} {item.get('name', 'Без названия')}\n"
        if item.get("desc"):
            msg += f"   └ {item['desc'][:80]}...\n"
        if item.get("file_url"):
            msg += "   📎 Приложен файл\n"

    for admin in ADMIN_IDS:
        try:
            await bot.send_message(admin, msg, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Failed to notify admin {admin}: {e}")

    return {"status": "ok", "order_ids": order_ids, "discount": discount}


@app.get("/api/get_orders")
async def get_orders_api(user_id: int):
    """
    Список заказов.
    Если user_id = админ → возвращаем все заказы.
    """
    is_admin = user_id in ADMIN_IDS
    orders = get_orders(None if is_admin else user_id)

    # добавляем файлы к каждому заказу
    for order in orders:
        order["files"] = get_order_files(order["id"])

    return {"orders": orders, "is_admin": is_admin}


@app.post("/api/update_order")
async def update_order_api(data: dict):
    """Обновление заказа (цена, статус, комментарий, оплата). Только админ."""
    admin_id = data.get("admin_id")
    if admin_id not in ADMIN_IDS:
        return {"status": "error", "message": "Нет прав"}

    order_id = data.get("order_id")
    user_id = data.get("user_id")
    price = data.get("price", 0)
    status = data.get("status", "")
    admin_comment = data.get("admin_comment", "")
    is_paid = data.get("is_paid", False)

    update_order(order_id, price, status, admin_comment, is_paid)

    # --- Уведомление пользователю в Telegram
    status_names = {
        "wait_price": "На оценке",
        "wait_payment": "Ожидает оплаты",
        "in_progress": "В работе",
        "ready": "Готов"
    }
    text = f"📦 <b>Заказ #{order_id}</b>\n\nСтатус: <b>{status_names.get(status, status)}</b>"

    if status == "wait_payment" and price:
        text += f"\n\n💰 К оплате: <b>{price} ₽</b>\n💳 Карта: <code>{CARD_NUMBER}</code>"
    if status == "ready":
        text += "\n\n✅ Работа готова! Откройте мини‑приложение или напишите в поддержку."

    if user_id:
        try:
            await bot.send_message(user_id, text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Failed to notify user {user_id}: {e}")

    return {"status": "ok"}


@app.post("/api/delete_order")
async def delete_order_api(data: dict):
    admin_id = data.get("admin_id")
    if admin_id not in ADMIN_IDS:
        return {"status": "error", "message": "Нет прав"}
    order_id = data.get("order_id")
    delete_order(order_id)
    return {"status": "ok"}


@app.post("/api/add_order_file")
async def add_order_file_api(
    order_id: int = Form(...),
    admin_id: int = Form(...),
    file: UploadFile = File(...)
):
    """Прикрепление файла к заказу из mini‑app (админ)."""
    if admin_id not in ADMIN_IDS:
        return {"status": "error", "message": "Нет прав"}

    try:
        ext = os.path.splitext(file.filename)[1] if file.filename else ".bin"
        unique = f"order_{order_id}_{uuid.uuid4().hex}{ext}"
        path = os.path.join(UPLOAD_DIR, unique)

        data = await file.read()
        if len(data) > 20 * 1024 * 1024:
            return {"error": "Файл слишком большой (макс 20 МБ)"}

        async with aiofiles.open(path, "wb") as f:
            await f.write(data)

        file_url = f"/uploads/{unique}"
        add_order_file(order_id, file.filename or unique, file_url)
        return {"status": "ok", "file_url": file_url}
    except Exception as e:
        logger.error(f"add_order_file error: {e}")
        return {"error": str(e)}


@app.post("/api/check_promo")
async def check_promo_api(data: dict):
    """
    Проверка промокода из словаря PROMO_CODES без списания uses_left.
    Нужна для предварительного показа скидки в корзине.
    """
    code = (data.get("code") or "").strip().upper()
    if not code:
        return {"valid": False}

    promo = PROMO_CODES.get(code)
    if not promo:
        return {"valid": False}

    uses_left = promo.get("uses_left")
    if uses_left is not None and uses_left <= 0:
        return {"valid": False}

    return {"valid": True, "discount": int(promo.get("discount", 0))}


@app.get("/api/get_chat")
async def get_chat_api(user_id: int):
    return {"messages": get_chat_history(user_id)}


@app.post("/api/send_message")
async def send_message_api(data: dict):
    """
    Сообщение от пользователя из mini‑app в поддержку.
    """
    user_id = data.get("user_id")
    username = data.get("username", "")
    message = data.get("message", "")
    file_url = data.get("file_url", "")

    if not user_id:
        return {"status": "error"}

    add_chat_message(user_id, "user", message, file_url, username)

    # Уведомляем админов
    for admin in ADMIN_IDS:
        try:
            text = (
                "📩 <b>Новое сообщение</b>\n\n"
                f"👤 @{username} (ID: {user_id})\n"
                f"💬 {message}\n\n"
                "Ответьте через /chats"
            )
            if file_url and os.path.exists(file_url.lstrip("/")):
                local = file_url.lstrip("/")
                if local.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
                    await bot.send_photo(admin, FSInputFile(local), caption=text, parse_mode="HTML")
                else:
                    await bot.send_document(admin, FSInputFile(local), caption=text, parse_mode="HTML")
            else:
                await bot.send_message(admin, text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Failed to send msg to admin {admin}: {e}")

    return {"status": "ok"}


@app.post("/api/upload_file")
async def upload_file_api(file: UploadFile = File(...)):
    """Загрузка файла из mini‑app (чат, кастом‑заказ)."""
    try:
        ext = os.path.splitext(file.filename)[1] if file.filename else ".bin"
        unique = f"{uuid.uuid4().hex}{ext}"
        path = os.path.join(STATIC_DIR, unique)

        data = await file.read()
        if len(data) > 10 * 1024 * 1024:
            return {"error": "Файл слишком большой (макс 10 МБ)"}

        async with aiofiles.open(path, "wb") as f:
            await f.write(data)

        return {"file_url": f"/static/{unique}"}
    except Exception as e:
        logger.error(f"upload_file error: {e}")
        return {"error": str(e)}


@app.get("/health")
async def health():
    return {"status": "ok"}


# ========== ЗАПУСК БОТА И СЕРВЕРА ==========

async def start_bot():
    logger.info("🤖 Запуск телеграм‑бота...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


async def start_server():
    logger.info("🌐 Запуск веб‑сервера...")
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    logger.info("=" * 50)
    logger.info("🚀 LabX: бот + мини‑приложение")
    logger.info("=" * 50)
    await asyncio.gather(start_bot(), start_server())


if __name__ == "__main__":
    asyncio.run(main())