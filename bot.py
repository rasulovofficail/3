import asyncio
import aiosqlite
from datetime import date
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
import google.generativeai as genai
import io
from PIL import Image
import requests

# ================== SOZLAMALAR ==================
BOT_TOKEN = "8643380161:AAG6Uv0_dYBWTojeljFCXpra_1nWmOgYhi4"
ADMIN_ID = 8318241400
GEMINI_API_KEY = "AQ.Ab8RN6KBnVsYwHSRtcJBCgv5iHs_YeURWMt5N4IA-wT-oDcoyQ"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# ================== STATES ==================
class Learning(StatesGroup):
    choosing_level = State()
    waiting_step = State()
    waiting_next = State()
    evaluating = State()

# ================== DATABASE ==================
async def init_db():
    async with aiosqlite.connect("drawing_bot.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                is_vip INTEGER DEFAULT 0,
                beginner_count INTEGER DEFAULT 0,
                medium_count INTEGER DEFAULT 0,
                last_reset TEXT
            )""")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                name TEXT,
                level TEXT,
                current_step INTEGER DEFAULT 1,
                total_steps INTEGER,
                steps_text TEXT,
                status TEXT DEFAULT 'active'
            )""")
        await db.commit()

async def get_or_create_user(user_id: int):
    today = str(date.today())
    async with aiosqlite.connect("drawing_bot.db") as db:
        async with db.execute("SELECT last_reset, is_vip FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()

        if not row:
            is_vip = 1 if user_id == ADMIN_ID else 0
            await db.execute(
                "INSERT INTO users (user_id, is_vip, last_reset) VALUES (?, ?, ?)",
                (user_id, is_vip, today)
            )
            await db.commit()
        else:
            if row[0] != today:
                await db.execute(
                    "UPDATE users SET beginner_count=0, medium_count=0, last_reset=? WHERE user_id=?",
                    (today, user_id)
                )
                await db.commit()
            if user_id == ADMIN_ID and row[1] == 0:
                await db.execute("UPDATE users SET is_vip=1 WHERE user_id=?", (user_id,))
                await db.commit()

# ================== KEYBOARDS ==================
def main_menu():
    kb = ReplyKeyboardBuilder()
    kb.button(text="🎨 Rasm chizishni o‘rganish")
    kb.button(text="📂 O‘rganish jarayoni")
    kb.button(text="🔍 Rasmni baholash")
    kb.adjust(1)
    return kb.as_markup(resize_keyboard=True)

def levels_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🟢 Beginner — 5 ta/kun", callback_data="level_beginner")
    kb.button(text="🟡 Medium — 3 ta/kun", callback_data="level_medium")
    kb.button(text="🔴 Expert (VIP) — cheklovsiz", callback_data="level_expert")
    kb.button(text="◀️ Orqaga", callback_data="back_main")
    kb.adjust(1)
    return kb.as_markup()

def next_step_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="➡️ Keyingisi", callback_data="next_step")
    kb.button(text="⏹ To‘xtatish", callback_data="stop_project")
    return kb.as_markup()

# ================== AI (Gemini) ==================
async def generate_steps(level: str, topic: str):
    if level == "beginner":
        prompt = f"""Boshlang‘ich daraja uchun rasm chizishni o‘rgat.
Mavzu: {topic}
Faqat 5 yoki 6 ta juda sodda qadam yoz.
Har bir qadamni raqamlab yoz (1. 2. 3...).
Boshqa hech narsa yozma."""
        max_steps = 6
    elif level == "medium":
        prompt = f"""O‘rta daraja uchun rasm chizishni o‘rgat.
Mavzu: {topic}
Aniq 10 ta ketma-ket qadam yoz.
Har bir qadamni raqamlab yoz.
Boshqa hech narsa yozma."""
        max_steps = 10
    else:
        prompt = f"""Ekspert daraja. Murakkab rasmni sodda qilib o‘rgat.
Mavzu: {topic}
Aniq 20 ta qadam yoz.
Har bir qadamni raqamlab yoz.
Boshqa hech narsa yozma."""
        max_steps = 20

    response = model.generate_content(prompt)
    text = response.text
    steps = [line.strip() for line in text.split("\n") if line.strip() and (line[0].isdigit() or line.startswith("-"))]
    return steps[:max_steps]

async def evaluate_drawing(image_url: str):
    img_data = requests.get(image_url).content
    img = Image.open(io.BytesIO(img_data))

    prompt = """Sen professional rassom va sabrli o‘qituvchisan.
Foydalanuvchi chizgan rasmni chuqur, lekin oddiy tilda tahlil qil.
Akademik terminlardan saqlan.

Javobni aniq shu formatda yoz:

✅ Yutuqlar va ijobiy tomonlari:
- ...

⚠️ Yo‘l qo‘yilgan kamchiliklar:
- ...

💡 Qanday to‘g‘rilash mumkin (aniq maslahatlar):
- ..."""

    response = model.generate_content([prompt, img])
    return response.text

# ================== HANDLERS ==================
@dp.message(CommandStart())
async def start(msg: Message, state: FSMContext):
    await get_or_create_user(msg.from_user.id)
    await state.clear()
    await msg.answer(
        "Salom! 🎨\nMen sizning rasm chizish ustozingizman.\n\nQuyidagi bo‘limni tanlang:",
        reply_markup=main_menu()
    )

@dp.message(F.text == "🎨 Rasm chizishni o‘rganish")
async def learn(msg: Message, state: FSMContext):
    await get_or_create_user(msg.from_user.id)
    await state.set_state(Learning.choosing_level)
    await msg.answer("Qaysi darajani tanlaysiz?", reply_markup=levels_kb())

@dp.callback_query(F.data.startswith("level_"))
async def choose_level(cb: CallbackQuery, state: FSMContext):
    level = cb.data.replace("level_", "")
    user_id = cb.from_user.id
    await get_or_create_user(user_id)

    async with aiosqlite.connect("drawing_bot.db") as db:
        async with db.execute("SELECT is_vip, beginner_count, medium_count FROM users WHERE user_id=?", (user_id,)) as cur:
            is_vip, beg, med = await cur.fetchone()

    if level == "beginner" and beg >= 5:
        return await cb.answer("Bugungi limit tugadi (5 ta)!", show_alert=True)
    if level == "medium" and med >= 3:
        return await cb.answer("Bugungi limit tugadi (3 ta)!", show_alert=True)
    if level == "expert" and not is_vip:
        return await cb.answer("Faqat VIP foydalanuvchilar uchun!", show_alert=True)

    await cb.message.edit_text(
        f"{'🟢 Beginner' if level=='beginner' else '🟡 Medium' if level=='medium' else '🔴 Expert'} tanlandi.\n\n"
        "Nima chizmoqchisiz? (masalan: mashina, uy, qiz yuzi...)"
    )
    await state.update_data(level=level)
    await state.set_state(Learning.waiting_step)

@dp.message(Learning.waiting_step)
async def start_project(msg: Message, state: FSMContext):
    data = await state.get_data()
    level = data["level"]
    topic = msg.text.strip()

    await msg.answer("Qadamlarni tayyorlayapman... ⏳")
    steps = await generate_steps(level, topic)
    total = len(steps)
    name = f"{level.capitalize()} — {topic[:30]}"

    async with aiosqlite.connect("drawing_bot.db") as db:
        cur = await db.execute(
            "INSERT INTO projects (user_id, name, level, current_step, total_steps, steps_text) VALUES (?,?,?,1,?,?)",
            (msg.from_user.id, name, level, total, "\n".join(steps))
        )
        project_id = cur.lastrowid

        if level == "beginner":
            await db.execute("UPDATE users SET beginner_count = beginner_count + 1 WHERE user_id=?", (msg.from_user.id,))
        elif level == "medium":
            await db.execute("UPDATE users SET medium_count = medium_count + 1 WHERE user_id=?", (msg.from_user.id,))
        await db.commit()

    await state.update_data(project_id=project_id, steps=steps, current=1, total=total)
    await msg.answer(
        f"📂 <b>{name}</b>\n\n<b>1-qadam:</b>\n{steps[0]}\n\nChizib bo‘lgach «Keyingisi» ni bosing.",
        reply_markup=next_step_kb(),
        parse_mode="HTML"
    )
    await state.set_state(Learning.waiting_next)

@dp.callback_query(F.data == "next_step")
async def next_step(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    current = data["current"]
    total = data["total"]
    steps = data["steps"]
    project_id = data["project_id"]

    if current >= total:
        await cb.message.edit_text(
            "🎉 Tabriklayman! Chizishni tugatdingiz!\n\nEndi «🔍 Rasmni baholash» orqali natijangizni yuboring."
        )
        async with aiosqlite.connect("drawing_bot.db") as db:
            await db.execute("UPDATE projects SET status='finished', current_step=? WHERE id=?", (total, project_id))
            await db.commit()
        await state.clear()
        return

    current += 1
    await state.update_data(current=current)
    async with aiosqlite.connect("drawing_bot.db") as db:
        await db.execute("UPDATE projects SET current_step=? WHERE id=?", (current, project_id))
        await db.commit()

    await cb.message.edit_text(
        f"<b>{current}-qadam:</b>\n{steps[current-1]}\n\nChizib bo‘lgach «Keyingisi» ni bosing.",
        reply_markup=next_step_kb(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "stop_project")
async def stop_project(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("Loyiha to‘xtatildi. «📂 O‘rganish jarayoni» dan davom ettirishingiz mumkin.")
    await state.clear()

@dp.message(F.text == "📂 O‘rganish jarayoni")
async def my_projects(msg: Message):
    async with aiosqlite.connect("drawing_bot.db") as db:
        async with db.execute(
            "SELECT id, name, current_step, total_steps, status FROM projects WHERE user_id=? ORDER BY id DESC LIMIT 10",
            (msg.from_user.id,)
        ) as cur:
            rows = await cur.fetchall()

    if not rows:
        return await msg.answer("Hozircha loyiha yo‘q.")

    text = "📂 Sizning loyihalaringiz:\n\n"
    kb = InlineKeyboardBuilder()
    for pid, name, cur, tot, status in rows:
        emoji = "✅" if status == "finished" else "🔄"
        text += f"{emoji} <b>{name}</b> ({cur}/{tot})\n"
        if status == "active":
            kb.button(text=f"Davom: {name[:22]}", callback_data=f"continue_{pid}")
    kb.adjust(1)
    await msg.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("continue_"))
async def continue_project(cb: CallbackQuery, state: FSMContext):
    project_id = int(cb.data.split("_")[1])
    async with aiosqlite.connect("drawing_bot.db") as db:
        async with db.execute(
            "SELECT name, current_step, total_steps, steps_text FROM projects WHERE id=?", (project_id,)
        ) as cur:
            row = await cur.fetchone()

    if not row:
        return await cb.answer("Loyiha topilmadi", show_alert=True)

    name, current, total, steps_text = row
    steps = steps_text.split("\n")
    await state.update_data(project_id=project_id, steps=steps, current=current, total=total)

    await cb.message.edit_text(
        f"📂 <b>{name}</b>\n\n<b>{current}-qadam:</b>\n{steps[current-1]}",
        reply_markup=next_step_kb(),
        parse_mode="HTML"
    )
    await state.set_state(Learning.waiting_next)

@dp.message(F.text == "🔍 Rasmni baholash")
async def eval_start(msg: Message, state: FSMContext):
    await state.set_state(Learning.evaluating)
    await msg.answer("Chizgan rasmingizni yuboring. Men uni tahlil qilaman.")

@dp.message(Learning.evaluating, F.photo)
async def eval_photo(msg: Message, state: FSMContext):
    file = await bot.get_file(msg.photo[-1].file_id)
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
    await msg.answer("Tahlil qilyapman... 🔍")
    result = await evaluate_drawing(url)
    await msg.answer(result)
    await state.clear()

@dp.message(Learning.evaluating)
async def eval_wrong(msg: Message):
    await msg.answer("Iltimos, rasm (foto) yuboring.")

@dp.callback_query(F.data == "back_main")
async def back(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.delete()
    await cb.message.answer("Asosiy menyu:", reply_markup=main_menu())

# ================== ADMIN ==================
@dp.message(Command("setvip"))
async def set_vip(msg: Message):
    if msg.from_user.id != ADMIN_ID:
        return
    try:
        uid = int(msg.text.split()[1])
        async with aiosqlite.connect("drawing_bot.db") as db:
            await db.execute("UPDATE users SET is_vip=1 WHERE user_id=?", (uid,))
            await db.commit()
        await msg.answer(f"✅ {uid} VIP qilindi.")
    except:
        await msg.answer("Foydalanish: /setvip 123456789")

@dp.message(Command("delvip"))
async def del_vip(msg: Message):
    if msg.from_user.id != ADMIN_ID:
        return
    try:
        uid = int(msg.text.split()[1])
        async with aiosqlite.connect("drawing_bot.db") as db:
            await db.execute("UPDATE users SET is_vip=0 WHERE user_id=?", (uid,))
            await db.commit()
        await msg.answer(f"❌ {uid} VIPdan olindi.")
    except:
        await msg.answer("Foydalanish: /delvip 123456789")

# ================== ISHGA TUSHIRISH ==================
async def main():
    await init_db()
    print("Bot ishga tushdi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
