import asyncio
import logging
import json
import os
import io
import re
import sqlite3
from datetime import datetime
import pytz  
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

import gspread
import openpyxl 
import pandas as pd
from oauth2client.service_account import ServiceAccountCredentials

# --- SOZLAMALAR ---
BOT_TOKEN = "8482178284:AAGzq9lzZEV6JlOkBA3_TvDcX37NQA_uB_M"
SUPER_ADMINS = [8317043750]  # Super Adminlar

PAYMENTS_GROUP_LINK = "https://t.me/isbot111"  
GOOGLE_SHEET_NAME = "Openbudjet"  
UZ_TZ = pytz.timezone('Asia/Tashkent')

# --- LOGGING VA BOT INITIALIZATSIYASI ---
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

claimed_users = {}
claimed_admin_names = {}
admin_message_ids = {}
payment_message_ids = {}  # To'lov adminlari xabarlarini boshqarish uchun

# --- SQLITE BAZA STRUKTURASI ---
def init_db():
    conn = sqlite3.connect("mailing_users.db")
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, joined_at TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS extra_admins (admin_id INTEGER PRIMARY KEY)")
    cursor.execute("CREATE TABLE IF NOT EXISTS payment_admins (admin_id INTEGER PRIMARY KEY)")
    cursor.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('start_time', '07:00')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('end_time', '23:00')")
    cursor.execute("CREATE TABLE IF NOT EXISTS admin_stats (admin_id INTEGER, action_type TEXT, count INTEGER DEFAULT 0, PRIMARY KEY (admin_id, action_type))")
    conn.commit()
    conn.close()

# --- BAZA BILAN ISHLASH FUNKSIYALARI ---
def add_user_to_db(user_id):
    try:
        conn = sqlite3.connect("mailing_users.db")
        cursor = conn.cursor()
        now = datetime.now(UZ_TZ).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("INSERT OR IGNORE INTO users (user_id, joined_at) VALUES (?, ?)", (user_id, now))
        conn.commit(); conn.close()
    except Exception as e: print(f"❌ SQLite xatolik: {e}")

def get_all_db_users():
    conn = sqlite3.connect("mailing_users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users

def get_extra_admins():
    conn = sqlite3.connect("mailing_users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT admin_id FROM extra_admins")
    admins = [row[0] for row in cursor.fetchall()]
    conn.close()
    return admins

def get_payment_admins():
    conn = sqlite3.connect("mailing_users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT admin_id FROM payment_admins")
    admins = [row[0] for row in cursor.fetchall()]
    conn.close()
    return admins

def add_extra_admin(admin_id):
    conn = sqlite3.connect("mailing_users.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO extra_admins (admin_id) VALUES (?)", (admin_id,))
    conn.commit(); conn.close()
    return True

def remove_extra_admin(admin_id):
    conn = sqlite3.connect("mailing_users.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM extra_admins WHERE admin_id = ?", (admin_id,))
    conn.commit(); conn.close()
    return True

def add_payment_admin(admin_id):
    conn = sqlite3.connect("mailing_users.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO payment_admins (admin_id) VALUES (?)", (admin_id,))
    conn.commit(); conn.close()
    return True

def remove_payment_admin(admin_id):
    conn = sqlite3.connect("mailing_users.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM payment_admins WHERE admin_id = ?", (admin_id,))
    conn.commit(); conn.close()
    return True

def get_db_setting(key, default):
    conn = sqlite3.connect("mailing_users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else default

def set_db_setting(key, value):
    conn = sqlite3.connect("mailing_users.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit(); conn.close()
    return True

def increment_admin_stat(admin_id, action_type):
    conn = sqlite3.connect("mailing_users.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO admin_stats (admin_id, action_type, count) VALUES (?, ?, 1) ON CONFLICT(admin_id, action_type) DO UPDATE SET count = count + 1", (admin_id, action_type))
    conn.commit(); conn.close()

def get_admin_stats_text():
    conn = sqlite3.connect("mailing_users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT admin_id, action_type, count FROM admin_stats")
    rows = cursor.fetchall()
    conn.close()
    if not rows: return "Adminlar ish statistikasi: Hozircha ma'lumot yo'q."
    data = {}
    for r in rows:
        a_id, act, cnt = r
        if a_id not in data: data[a_id] = {}
        data[a_id][act] = cnt
    text = "📊 <b>Adminlar va Operatorlar Ish Statistikasi:</b>\n\n"
    for a_id, acts in data.items():
        text += f"👤 Admin ID: <code>{a_id}</code>\n"
        text += f" ├ Band qilingan raqamlar: {acts.get('claim', 0)} ta\n"
        text += f" ├ Tasdiqlangan (Muvaffaqiyatli): {acts.get('success', 0)} ta\n"
        text += f" ├ To'lov qilindi: {acts.get('paid', 0)} ta\n"
        text += f" └ Rad etilgan (Avval ovoz bergan): {acts.get('already', 0)} ta\n\n"
    return text

init_db()

def get_all_admins():
    return list(set(SUPER_ADMINS + get_extra_admins() + get_payment_admins()))

def is_working_hours():
    now_uz = datetime.now(UZ_TZ).time()
    start_time = datetime.strptime(get_db_setting('start_time', '07:00'), "%H:%M").time()
    end_time = datetime.strptime(get_db_setting('end_time', '23:00'), "%H:%M").time()
    if start_time <= end_time: return start_time <= now_uz <= end_time
    return now_uz >= start_time or now_uz <= end_time

# --- GOOGLE SHEETS ---
def get_google_sheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    google_creds_env = os.getenv("GOOGLE_CREDS")
    if google_creds_env:
        creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(google_creds_env), scope)
    else:
        creds = ServiceAccountCredentials.from_json_keyfile_name("open.json", scope)
    return gspread.authorize(creds).open(GOOGLE_SHEET_NAME).sheet1

def log_to_sheets(user_id, full_name="", username="", phone="", code="", card="", status="", admin_name="", referrer_id="", payment_admin=""):
    try:
        sheet = get_google_sheet()
        all_records = sheet.get_all_values()
        now = datetime.now(UZ_TZ).strftime("%Y-%m-%d %H:%M:%S")
        username_str = f"@{username}" if username else "Mavjud emas"
        
        row_index = -1
        for idx, row in enumerate(all_records):
            if len(row) >= 4 and row[0] == str(user_id) and row[3] == str(phone):
                row_index = idx + 1
                break
        
        if row_index != -1:
            if code: sheet.update_cell(row_index, 5, str(code))
            if card: sheet.update_cell(row_index, 6, str(card))
            if status: sheet.update_cell(row_index, 7, status)
            sheet.update_cell(row_index, 8, now)
            if admin_name: sheet.update_cell(row_index, 9, admin_name)
            if referrer_id and (len(row) < 10 or not row[9]): sheet.update_cell(row_index, 10, str(referrer_id))
            if payment_admin: sheet.update_cell(row_index, 11, payment_admin)
        else:
            sheet.append_row([str(user_id), full_name, username_str, str(phone), str(code), str(card), status, now, admin_name, str(referrer_id), payment_admin])
    except Exception as e: print(f"❌ Sheets xatolik: {e}")

# --- FSM STATES ---
class VoteState(StatesGroup):
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_screenshot = State()
    waiting_for_admin_check = State()  
    waiting_for_card = State()
    waiting_for_card_name = State()  # ✨ YANGI: Karta egasining ismini kutish holati

class AdminState(StatesGroup):
    waiting_for_broadcast_msg = State()
    waiting_for_new_admin = State()
    waiting_for_del_admin = State()
    waiting_for_new_pay_admin = State()
    waiting_for_del_pay_admin = State()
    waiting_for_work_hours = State()

# --- KLAVIATURALAR ---
def main_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="🗳 Ovoz berish")
    builder.button(text="👥 Taklifnomalar (Referal)") 
    builder.button(text="💰 To'lovlar muvaffaqiyati")
    builder.button(text="🙋‍♂️ Yordam")
    builder.adjust(1, 1, 2)
    return builder.as_markup(resize_keyboard=True)

def admin_menu(user_id):
    builder = ReplyKeyboardBuilder()
    builder.button(text="📊 Jonli Statistika")
    builder.button(text="👥 Adminlar Ishi")
    if user_id in SUPER_ADMINS:
        builder.button(text="📥 Excel Hisobot (.xlsx)")
        builder.button(text="📢 Xabar yuborish (Mailing)") 
        builder.button(text="⚙️ Ish Vaqtini Sozlash")
        builder.button(text="➕ Operator Qo'shish")
        builder.button(text="➖ Operator O'chirish")
        builder.button(text="💳 To'lov Admin Qo'shish")
        builder.button(text="❌ To'lov Admin O'chirish")
    builder.button(text="⬅️ Bosh menyu")
    if user_id in SUPER_ADMINS: builder.adjust(2, 2, 1, 2, 2, 1)
    else: builder.adjust(2, 1)
    return builder.as_markup(resize_keyboard=True)

def phone_share_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="📱 Telefon raqamni yuborish", request_contact=True)
    builder.button(text="❌ Bekor qilish")
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)

# --- BUYRUQLAR INTERFEYSI ---
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()  
    user_id = message.from_user.id
    if user_id not in get_all_admins(): add_user_to_db(user_id)
    
    args = message.text.split()
    if len(args) > 1 and args[1].isdigit() and int(args[1]) != user_id:
        await state.update_data(referrer_id=args[1])

    if user_id in get_all_admins():
        await message.answer("🔑 <b>Admin panelga xush kelibsiz!</b>", reply_markup=admin_menu(user_id), parse_mode="HTML")
    else:
        await message.answer("👋 Assalomu alaykum! Open Budget ovoz berish botiga xush kelibsiz.\nQORABAYIR MFYga o'z ovozingizni berib, kafolatlangan to'lovga ega bo'ling.", reply_markup=main_menu())

@dp.message(F.text == "⬅️ Bosh menyu")
async def back_to_main(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    await state.clear()
    if user_id in get_all_admins(): await message.answer("Admin menyusi:", reply_markup=admin_menu(user_id))
    else: await message.answer("Bosh menyuga qaytildi.", reply_markup=main_menu())

# --- REFERAL TIZIMI ---
@dp.message(F.text == "👥 Taklifnomalar (Referal)")
async def process_referral_info(message: types.Message):
    user_id = message.from_user.id
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user_id}"
    waiting_msg = await message.answer("🔄 Takliflaringiz soni hisoblanmoqda...")
    
    referral_count = 0
    try:
        sheet = get_google_sheet()
        for row in sheet.get_all_values():
            if len(row) >= 10 and row[9] == str(user_id): referral_count += 1
    except Exception: pass

    text = f"<b>👥 Do'stlarni taklif qiling va qo'shimcha daromad oling!</b>\n\n📊 Siz taklif qilgan jami do'stlaringiz: {referral_count} ta\n\n🔗 Havolangiz:\n<code>{ref_link}</code>"
    ikb = InlineKeyboardBuilder()
    ikb.button(text="🚀 Do'stlarga yuborish", url=f"https://t.me/share/url?url={ref_link}&text=Ovoz%20bering!")
    await waiting_msg.delete()
    await message.answer(text, parse_mode="HTML", reply_markup=ikb.as_markup())

# --- STATISTIKA VA ADMIN BOSHQARUVLARI ---
@dp.message(F.text == "📊 Jonli Statistika")
async def show_detailed_stats(message: types.Message):
    if message.from_user.id not in get_all_admins(): return
    waiting_msg = await message.answer("🔄 Statistika hisoblanmoqda...")
    try:
        db_users = len(get_all_db_users())
        all_rows = get_google_sheet().get_all_values()[1:]
        success = sum(1 for r in all_rows if len(r) >= 7 and "Muvaffaqiyatli" in r[6])
        rejected = sum(1 for r in all_rows if len(r) >= 7 and ("Avval" in r[6] or "rad" in r[6].lower()))
        
        stats_text = f"📊 **Jonli Real-Vaqt Statistikasi**\n\n👤 Bot a'zolari: {db_users}\n📥 Jami arizalar: {len(all_rows)}\n🟢 Muvaffaqiyatli: {success}\n🔴 Rad etilganlar: {rejected}"
        await waiting_msg.delete()
        await message.answer(stats_text, parse_mode="Markdown")
    except Exception as e: await waiting_msg.edit_text(f"❌ Xatolik: {e}")

@dp.message(F.text == "👥 Adminlar Ishi")
async def show_admin_work_stats(message: types.Message):
    if message.from_user.id not in get_all_admins(): return
    await message.answer(get_admin_stats_text(), parse_mode="HTML")

@dp.message(F.text == "⚙️ Ish Vaqtini Sozlash")
async def set_hours_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in SUPER_ADMINS: return
    await message.answer(f"⚙️ Format: `08:00-22:00` shaklida kiriting:", parse_mode="Markdown")
    await state.set_state(AdminState.waiting_for_work_hours)

@dp.message(AdminState.waiting_for_work_hours)
async def set_hours_finish(message: types.Message, state: FSMContext):
    await state.clear()
    text = message.text.strip()
    if re.match(r"^([0-1]?[0-9]|2[0-3]):[0-5][0-9]-([0-1]?[0-9]|2[0-3]):[0-5][0-9]$", text):
        sh, eh = text.split("-")
        set_db_setting('start_time', sh); set_db_setting('end_time', eh)
        await message.answer(f"✅ Ish vaqti o'rnatildi: {sh} - {eh}", reply_markup=admin_menu(message.from_user.id))
    else:
        await message.answer("❌ Format xato. Misol: 07:00-23:00", reply_markup=admin_menu(message.from_user.id))

@dp.message(F.text == "➕ Operator Qo'shish")
async def add_admin_start(message: types.Message, state: FSMContext):
    if message.from_user.id in SUPER_ADMINS:
        await message.answer("Yangi operatorning Telegram ID raqamini kiriting:")
        await state.set_state(AdminState.waiting_for_new_admin)

@dp.message(AdminState.waiting_for_new_admin)
async def add_admin_finish(message: types.Message, state: FSMContext):
    await state.clear()
    if message.text.isdigit() and add_extra_admin(int(message.text)):
        await message.answer("✅ Operator ro'yxatga qo'shildi.", reply_markup=admin_menu(message.from_user.id))
    else: await message.answer("❌ ID xato.", reply_markup=admin_menu(message.from_user.id))

@dp.message(F.text == "➖ Operator O'chirish")
async def del_admin_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in SUPER_ADMINS: return
    text = "O'chirish uchun ID yuboring:\n" + "\n".join([f"• <code>{a}</code>" for a in get_extra_admins()])
    await message.answer(text, parse_mode="HTML"); await state.set_state(AdminState.waiting_for_del_admin)

@dp.message(AdminState.waiting_for_del_admin)
async def del_admin_finish(message: types.Message, state: FSMContext):
    await state.clear()
    if message.text.isdigit() and remove_extra_admin(int(message.text)):
        await message.answer("✅ Operator o'chirildi.", reply_markup=admin_menu(message.from_user.id))
    else: await message.answer("❌ Topilmadi.", reply_markup=admin_menu(message.from_user.id))

# --- DINAMIK TO'LOV ADMINLARINI BOSHQARISH ---
@dp.message(F.text == "💳 To'lov Admin Qo'shish")
async def add_pay_admin_start(message: types.Message, state: FSMContext):
    if message.from_user.id in SUPER_ADMINS:
        await message.answer("To'lov bilan shug'ullanadigan adminning **Telegram ID** raqamini yuboring:")
        await state.set_state(AdminState.waiting_for_new_pay_admin)

@dp.message(AdminState.waiting_for_new_pay_admin)
async def add_pay_admin_finish(message: types.Message, state: FSMContext):
    await state.clear()
    if message.text.isdigit() and add_payment_admin(int(message.text)):
        await message.answer("✅ Yangi To'lov Admini muvaffaqiyatli qo'shildi!", reply_markup=admin_menu(message.from_user.id))
    else: await message.answer("❌ Noto'g'ri ID raqam.", reply_markup=admin_menu(message.from_user.id))

@dp.message(F.text == "❌ To'lov Admin O'chirish")
async def del_pay_admin_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in SUPER_ADMINS: return
    p_admins = get_payment_admins()
    if not p_admins: 
        await message.answer("Hozirda hech qanday to'lov admini yo'q."); return
    text = "O'chirmoqchi bo'lgan to'lov adminining ID raqamini yuboring:\n" + "\n".join([f"• <code>{a}</code>" for a in p_admins])
    await message.answer(text, parse_mode="HTML"); await state.set_state(AdminState.waiting_for_del_pay_admin)

@dp.message(AdminState.waiting_for_del_pay_admin)
async def del_pay_admin_finish(message: types.Message, state: FSMContext):
    await state.clear()
    if message.text.isdigit() and remove_payment_admin(int(message.text)):
        await message.answer("✅ To'lov admini muvaffaqiyatli o'chirildi.", reply_markup=admin_menu(message.from_user.id))
    else: await message.answer("❌ Xatolik yuz berdi.", reply_markup=admin_menu(message.from_user.id))

# --- MAILING VA EXCEL REPORT ---
@dp.message(F.text == "📢 Xabar yuborish (Mailing)")
async def start_broadcast(message: types.Message, state: FSMContext):
    if message.from_user.id in SUPER_ADMINS:
        await message.answer("Xabarni kiriting:"); await state.set_state(AdminState.waiting_for_broadcast_msg)

@dp.message(AdminState.waiting_for_broadcast_msg)
async def process_broadcast_message(message: types.Message, state: FSMContext):
    await state.clear()
    s_msg = await message.answer("📢 Tarqatish boshlandi...")
    sc, fc = 0, 0
    for u_id in get_all_db_users():
        try:
            if int(u_id) in get_all_admins(): continue
            await bot.send_message(chat_id=int(u_id), text=message.text)
            sc += 1; await asyncio.sleep(0.05)
        except Exception: fc += 1
    await s_msg.edit_text(f"✅ Tugadi.\n🟢 Yetkazildi: {sc}\n🔴 Yetkazilmadi: {fc}")

@dp.message(F.text == "📥 Excel Hisobot (.xlsx)")
async def send_excel_report(message: types.Message):
    if message.from_user.id not in SUPER_ADMINS: return
    waiting_msg = await message.answer("🔄 Yuklanmoqda...")
    try:
        all_data = get_google_sheet().get_all_values()
        wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Hisobot"
        for row in all_data: ws.append(row)
        buf = io.BytesIO(); wb.save(buf); buf.seek(0)
        await waiting_msg.delete()
        await message.answer_document(document=types.BufferedInputFile(buf.getvalue(), filename="Hisobot.xlsx"), caption="📊 Barcha arizalar hisoboti.")
    except Exception as e: await waiting_msg.edit_text(f"❌ Xatolik: {e}")

@dp.message(F.text == "💰 To'lovlar muvaffaqiyati")
async def process_payments_info(message: types.Message):
    await message.answer(f"<b>💰 To'lovlar Muvaffaqiyati Guruhimiz:</b>\n{PAYMENTS_GROUP_LINK}", parse_mode="HTML", reply_markup=InlineKeyboardBuilder().button(text="🔗 Guruh", url=PAYMENTS_GROUP_LINK).as_markup())

@dp.message(F.text == "🙋‍♂️ Yordam")
async def process_help(message: types.Message):
    await message.answer("<b>🙋‍♂️ Yordam markazi:</b>", parse_mode="HTML", reply_markup=InlineKeyboardBuilder().button(text="✍️ Operator", url="https://t.me/soibnazarov07").as_markup())


# =====================================================================
# 🔥 OVOZ BERISH VA RAQAM DUBLIKATLARINI REAL-TIME FILTRLASH 🔥
# =====================================================================

@dp.message(F.text == "🗳 Ovoz berish")
async def start_voting(message: types.Message, state: FSMContext):
    if not is_working_hours() and message.from_user.id not in SUPER_ADMINS:
        await message.answer(f"🌙 Bot hozirda yopiq! Ish vaqti: {get_db_setting('start_time', '07:00')} - {get_db_setting('end_time', '23:00')}")
        return
    await state.clear()
    await message.answer("Format: +998901234567. Telefon raqamingizni kiriting:", reply_markup=phone_share_keyboard())
    await state.set_state(VoteState.waiting_for_phone)

@dp.message(F.text == "❌ Bekor qilish", VoteState.waiting_for_phone)
async def cancel_voting(message: types.Message, state: FSMContext):
    await state.clear(); await message.answer("Bekor qilindi.", reply_markup=main_menu())

@dp.message(VoteState.waiting_for_phone, F.contact | F.text)
async def process_phone(message: types.Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear(); await message.answer("Bekor qilindi.", reply_markup=main_menu()); return

    phone = message.contact.phone_number if message.contact else message.text.strip().replace(" ", "")
    if re.match(r"^998\d{9}$", phone): phone = "+" + phone
    elif re.match(r"^\d{9}$", phone): phone = "+998" + phone
    if not re.match(r"^\+998\d{9}$", phone):
        await message.answer("⚠️ Noto'g'ri format. Qayta kiriting:"); return

    # JADVALDAN DUBLIKAT RAQAMNI BARCHA FAOL HOLATLAR (TO'LOV JARAYONIDA HAM) BO'YICHA TEKSHIRISH
    try:
        all_records = get_google_sheet().get_all_values()
        for row in all_records:
            if len(row) >= 7 and row[3] == str(phone):
                if row[6] in ["Admin qabul qildi", "Kod kiritildi", "Kod tasdiqlandi", "Skrinshot keldi", "Muvaffaqiyatli", "To'lov jarayonida", "To'lov qilindi"]:
                    await message.answer("❌ Ushbu raqamdan avval ovoz berilgan yoki jarayon yakunlanmagan!", reply_markup=main_menu())
                    await state.clear(); return
    except Exception as e: print(f"Sheets tekshirishda xato: {e}")

    user_id, full_name, username = message.from_user.id, message.from_user.full_name, message.from_user.username
    data = await state.get_data(); r_id = data.get("referrer_id", "")
    await state.update_data(phone=phone, full_name=full_name, username=username)
    log_to_sheets(user_id=user_id, full_name=full_name, username=username, phone=phone, status="Raqam kiritildi", referrer_id=r_id)

    builder = InlineKeyboardBuilder().button(text="✅ Qabul qilish (Band qilish)", callback_data=f"claim_{user_id}")
    admin_message_ids[user_id] = {}
    for admin in get_all_admins():
        if admin in get_payment_admins(): continue 
        try:
            msg = await bot.send_message(admin, f"📱 <b>Yangi raqam:</b>\n👤 Foydalanuvchi: {full_name}\n📞 Raqam: {phone}", parse_mode="HTML", reply_markup=builder.as_markup())
            admin_message_ids[user_id][admin] = msg.message_id
        except Exception: pass
    await message.answer("Raqamingiz qabul qilindi. Operatorlar ko'rib chiqmoqda...")

# --- OPERATOR BOSHQARUVI VA SMS KOD ---
@dp.callback_query(F.data.startswith("claim_"))
async def admin_claim(callback: types.CallbackQuery):
    user_id = int(callback.data.split("_")[1])
    admin_id, admin_name = callback.from_user.id, callback.from_user.full_name
    if user_id in claimed_users:
        await callback.answer("❌ Kech qoldingiz! Band qilingan.", show_alert=True); return

    claimed_users[user_id] = admin_id; claimed_admin_names[user_id] = admin_name
    increment_admin_stat(admin_id, 'claim')
    
    u_state = dp.fsm.resolve_context(bot, chat_id=user_id, user_id=user_id)
    await u_state.set_state(VoteState.waiting_for_code)
    await u_state.update_data(admin_id=admin_id)
    u_data = await u_state.get_data()

    log_to_sheets(user_id=user_id, phone=u_data.get("phone"), status="Admin qabul qildi", admin_name=admin_name, referrer_id=u_data.get("referrer_id"))
    
    if user_id in admin_message_ids:
        for a_id, m_id in admin_message_ids[user_id].items():
            try: await bot.edit_message_text(text=f"📱 Raqam keldi\n🔒 <b>[{admin_name}] qabul qildi!</b>", chat_id=a_id, message_id=m_id, parse_mode="HTML")
            except Exception: pass

    await bot.send_message(user_id, "Sizning raqamingiz kiritildi. SMS kodni yuboring. ⏱ 2:00 daqiqa", parse_mode="HTML")

@dp.message(VoteState.waiting_for_code)
async def process_code(message: types.Message, state: FSMContext):
    code = message.text; data = await state.get_data(); user_id = message.from_user.id
    await state.update_data(code=code)
    log_to_sheets(user_id=user_id, phone=data.get("phone"), code=code, status="Kod kiritildi", admin_name=claimed_admin_names.get(user_id))

    verify_kb = InlineKeyboardBuilder().button(text="✅ To'g'ri", callback_data=f"v_correct_{user_id}").button(text="❌ Xato", callback_data=f"v_wrong_{user_id}").adjust(2)
    try: await bot.send_message(data.get("admin_id"), f"🔢 Kod keldi: <code>{code}</code>\nTelefon: {data.get('phone')}", parse_mode="HTML", reply_markup=verify_kb.as_markup())
    except Exception: pass
    await message.answer("Kod tekshirilmoqda...")

@dp.callback_query(F.data.startswith("v_"))
async def handle_code_verification(callback: types.CallbackQuery):
    _, status, user_id = callback.data.split("_")
    user_id = int(user_id)
    u_state = dp.fsm.resolve_context(bot, chat_id=user_id, user_id=user_id)
    data = await u_state.get_data()

    if status == "correct":
        log_to_sheets(user_id=user_id, phone=data.get("phone"), status="Kod tasdiqlandi", admin_name=callback.from_user.full_name)
        await callback.message.edit_text("🟢 Kod to'g'ri deb belgilandi."); await u_state.set_state(VoteState.waiting_for_screenshot)
        await bot.send_message(user_id, "🎉 Kod tasdiqlandi. SMS skrinshotini yuboring! 📸")
    else:
        log_to_sheets(user_id=user_id, phone=data.get("phone"), status="Kod xato", admin_name=callback.from_user.full_name)
        await callback.message.edit_text("🔴 Kod xato deb belgilandi.")
        await bot.send_message(user_id, "⚠️ Kod rad etildi. To'g'ri kodni qayta kiriting.")

# --- SKRINSHOT VA TASDIQLASH ---
@dp.message(VoteState.waiting_for_screenshot, F.photo)
async def process_screenshot(message: types.Message, state: FSMContext):
    p_id = message.photo[-1].file_id; data = await state.get_data(); user_id = message.from_user.id
    log_to_sheets(user_id=user_id, phone=data.get("phone"), status="Skrinshot keldi", admin_name=claimed_admin_names.get(user_id))

    builder = InlineKeyboardBuilder().button(text="🟢 Muvaffaqiyatli", callback_data=f"c_success_{user_id}").button(text="🔴 Avval ovoz bergan", callback_data=f"c_already_{user_id}").adjust(1)
    try: await bot.send_photo(data.get("admin_id"), p_id, caption=f"📸 Skrinshot keldi:\nRaqam: {data.get('phone')}", reply_markup=builder.as_markup())
    except Exception: pass
    await message.answer("Skrinshot yuborildi, kuting...")
    await state.set_state(VoteState.waiting_for_admin_check)

@dp.callback_query(F.data.startswith("c_"))
async def handle_admin_check(callback: types.CallbackQuery):
    _, action, user_id = callback.data.split("_")
    user_id = int(user_id)
    u_state = dp.fsm.resolve_context(bot, chat_id=user_id, user_id=user_id)
    data = await u_state.get_data()

    if action == "success":
        log_to_sheets(user_id=user_id, phone=data.get("phone"), status="Muvaffaqiyatli", admin_name=callback.from_user.full_name)
        increment_admin_stat(callback.from_user.id, 'success')
        await callback.message.edit_caption(caption="✅ Tasdiqlandi!")
        await u_state.set_state(VoteState.waiting_for_card)
        await bot.send_message(user_id, "Tabriklaymiz! Ovoz tasdiqlandi. 💳 Plastik karta raqamingizni yuboring:")
    else:
        log_to_sheets(user_id=user_id, phone=data.get("phone"), status="Avval ovoz bergan", admin_name=callback.from_user.full_name)
        increment_admin_stat(callback.from_user.id, 'already')
        await callback.message.edit_caption(caption="❌ Rad etildi (Avval ovoz bergan)")
        await u_state.clear(); await bot.send_message(user_id, "Uzr, bu raqamdan avval foydalanilgan.", reply_markup=main_menu())


# =====================================================================
# 💎 YANGILANGAN KARTA RAQAMI + KARTA EGASI ISMINI SURASH TIZIMI 💎
# =====================================================================

@dp.message(VoteState.waiting_for_card)
async def process_card(message: types.Message, state: FSMContext):
    clean_card = re.sub(r'\D', '', message.text)
    if len(clean_card) != 16 or not clean_card.startswith(('8600', '5614', '9860', '4444', '6262')):
        await message.answer("⚠️ Karta raqami xato. 16 xonali Uzcard/Humo karta raqamini qayta kiriting:"); return

    await state.update_data(card=clean_card)
    
    # Karta to'g'ri bo'lsa, endi karta egasining ismini so'raymiz
    await message.answer("👤 Karta egasining ism-familiyasini kiriting (Xatoliksiz, to'liq yozing):")
    await state.set_state(VoteState.waiting_for_card_name)

@dp.message(VoteState.waiting_for_card_name)
async def process_card_name(message: types.Message, state: FSMContext):
    card_name = message.text.strip()
    if len(card_name) < 3:
        await message.answer("⚠️ Ism juda qisqa. Iltimos, to'liq ism-familiyani kiriting:"); return

    data = await state.get_data()
    user_id = message.from_user.id
    phone = data.get("phone")
    clean_card = data.get("card")
    
    await state.update_data(card_name=card_name)

    # Google Sheets'ga karta ma'lumotlarini ism bilan birga yozamiz
    full_card_details = f"{clean_card} ({card_name})"
    log_to_sheets(user_id=user_id, phone=phone, card=full_card_details, status="To'lov jarayonida", admin_name=claimed_admin_names.get(user_id))

    # To'lov adminlarini aniqlash
    p_admins = get_payment_admins()
    if not p_admins: p_admins = SUPER_ADMINS

    pay_builder = InlineKeyboardBuilder().button(text="📥 To'lovni Qabul Qilish", callback_data=f"take_pay_{user_id}")
    payment_message_ids[user_id] = {}

    # TO'LOV ADMINLARIGA ISMI VA KARTASI BILAN BIRGA ARIZA YUBORISH
    for p_admin in p_admins:
        try:
            msg = await bot.send_message(
                chat_id=p_admin,
                text=f"🚨 <b>YANGI TO'LOV ARIZASI!</b>\n\n"
                     f"👤 Foydalanuvchi: {data.get('full_name')}\n"
                     f"📞 Telefon: {phone}\n"
                     f"💳 Karta: <code>{clean_card}</code>\n"
                     f"👤 Karta Egasi: <b>{card_name}</b>\n\n"
                     f"Kim birinchi qabul qilsa, o'sha admin to'lov qiladi.",
                parse_mode="HTML", reply_markup=pay_builder.as_markup()
            )
            payment_message_ids[user_id][p_admin] = msg.message_id
        except Exception: pass

    await message.answer("Ma'lumotlaringiz qabul qilindi. Tez orada hisobingizga pul o'tkaziladi. Rahmat!", reply_markup=main_menu())


# --- TO'LOV ADMINI MATNINI QABUL QILISH VA YAKUNLASH ---
@dp.callback_query(F.data.startswith("take_pay_"))
async def handle_take_payment(callback: types.CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split("_")[2])
    admin_id, admin_name = callback.from_user.id, callback.from_user.full_name

    u_state = dp.fsm.resolve_context(bot, chat_id=user_id, user_id=user_id)
    u_data = await u_state.get_data()

    sheet = get_google_sheet()
    records = sheet.get_all_values()
    current_status = ""
    for r in records:
        if len(r) >= 7 and r[0] == str(user_id) and r[3] == str(u_data.get("phone")):
            current_status = r[6]
            break

    if "To'lov qilindi" in current_status:
        await callback.answer("❌ Kech qoldingiz! Bu to'lov yakunlangan.", show_alert=True)
        try: await callback.message.delete()
        except Exception: pass
        return

    await callback.answer("Muvaffaqiyatli band qilindi!")
    log_to_sheets(user_id=user_id, phone=u_data.get("phone"), status="To'lov jarayonida", payment_admin=admin_name)

    # Boshqa to'lov adminlarida tugmani bloklash
    if user_id in payment_message_ids:
        for a_id, m_id in payment_message_ids[user_id].items():
            try:
                if a_id == admin_id: continue
                await bot.edit_message_text(chat_id=a_id, message_id=m_id, text=f"💳 To'lov arizasi\n🔒 <b>[{admin_name}] qabul qildi va ishlamoqda!</b>", reply_markup=None)
            except Exception: pass

    action_builder = InlineKeyboardBuilder()
    action_builder.button(text="✅ To'lov qilindi", callback_data=f"p_success_{user_id}")
    action_builder.button(text="❌ Qilinmadi (Rad)", callback_data=f"p_fail_{user_id}").adjust(2)

    await callback.message.edit_text(
        text=f"{callback.message.text}\n\n🟡 <b>Holat: Siz tomondan qabul qilindi. To'lovni bajaring va tasdiqlang:</b>",
        parse_mode="HTML", reply_markup=action_builder.as_markup()
    )

@dp.callback_query(F.data.startswith("p_"))
async def finalize_payment(callback: types.CallbackQuery):
    _, action, user_id = callback.data.split("_")
    user_id = int(user_id)
    admin_id, admin_name = callback.from_user.id, callback.from_user.full_name

    u_state = dp.fsm.resolve_context(bot, chat_id=user_id, user_id=user_id)
    u_data = await u_state.get_data()

    if action == "success":
        log_to_sheets(user_id=user_id, phone=u_data.get("phone"), status="To'lov qilindi", payment_admin=admin_name)
        increment_admin_stat(admin_id, 'paid')
        await callback.message.edit_text(text=f"{callback.message.text}\n\n✅ <b>Muvaffaqiyatli yakunlandi. Pul o'tkazildi!</b>", reply_markup=None)
        await callback.answer("Muvaffaqiyatli deb tasdiqladingiz!", show_alert=True)

        try: await bot.send_message(chat_id=user_id, text="💰 <b>Sizga pul o'tkazildi, hisobingizni tekshirishingiz mumkin!</b> Ovoz berganingiz uchun rahmat.", parse_mode="HTML")
        except Exception: pass

        ref_id = u_data.get("referrer_id")
        if ref_id and str(ref_id).isdigit():
            try: await bot.send_message(chat_id=int(ref_id), text=f"🎁 Do'stingiz (ID: {user_id}) to'lovdan o'tdi va sizga ham bonus o'tkazildi!")
            except Exception: pass

    elif action == "fail":
        log_to_sheets(user_id=user_id, phone=u_data.get("phone"), status="To'lov rad etildi (Qilinmadi)", payment_admin=admin_name)
        await callback.message.edit_text(text=f"{callback.message.text}\n\n❌ <b>To'lov rad etildi (qilinmadi) deb muhrlandi!</b>", reply_markup=None)
        await callback.answer("To'lov rad etildi.", show_alert=True)

        try: await bot.send_message(chat_id=user_id, text="❌ <b>Karta raqamingizda yoki to'lovda muammo bo'ldi.</b> Iltimos, qayta urinib ko'ring yoki operatorga murojaat qiling.", parse_mode="HTML")
        except Exception: pass

    if user_id in claimed_users: del claimed_users[user_id]
    if user_id in claimed_admin_names: del claimed_admin_names[user_id]
    if user_id in admin_message_ids: del admin_message_ids[user_id]
    if user_id in payment_message_ids: del payment_message_ids[user_id]
    await u_state.clear()

async def main(): await dp.start_polling(bot)
if __name__ == "__main__": asyncio.run(main())
