from __future__ import annotations

import asyncio
import logging
import time

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from sqlalchemy import func, select

from .config import get_settings
from .crypto import PayloadCrypto
from .db import make_engine, make_session_factory
from .logging import configure_logging
from .models import AppleChallenge, AppleJob, AuditLog, LedgerEntry, Order, User, Wallet, now_utc
from .orders import create_apple_order, create_or_get_user
from .wallet import InsufficientBalance, adjust_wallet, ensure_wallet

log = logging.getLogger("twoid.bot")
settings = get_settings()
engine = make_engine(settings.database_url)
SF = make_session_factory(engine)
crypto = PayloadCrypto(settings.encryption_key)


class CreateFlow(StatesGroup):
    email = State()
    password = State()
    first_name = State()
    last_name = State()
    confirm = State()


class AdminAdjustFlow(StatesGroup):
    target_user = State()
    amount = State()


class EmailOtpFlow(StatesGroup):
    order_id = State()
    otp = State()


def is_admin(user_id: int | None) -> bool:
    return settings.is_admin(user_id)


def main_keyboard(user_id: int | None = None):
    rows = [
        [KeyboardButton(text="🍎 ساخت Apple ID"), KeyboardButton(text="💰 کیف پول")],
        [KeyboardButton(text="📦 سفارش‌های من"), KeyboardButton(text="🛟 پشتیبانی")],
        [KeyboardButton(text="📧 ثبت کد ایمیل")],
    ]
    if is_admin(user_id):
        rows.append([KeyboardButton(text="🛠 مدیریت")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def confirm_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ ثبت سفارش", callback_data="order_confirm"),
                InlineKeyboardButton(text="❌ لغو", callback_data="order_cancel"),
            ]
        ]
    )


def admin_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 آمار", callback_data="admin_stats"),
                InlineKeyboardButton(text="👥 کاربران", callback_data="admin_users"),
            ],
            [
                InlineKeyboardButton(text="📦 سفارش‌ها", callback_data="admin_orders"),
                InlineKeyboardButton(text="💳 شارژ کیف پول", callback_data="admin_credit"),
            ],
            [
                InlineKeyboardButton(text="➖ کسر از کیف پول", callback_data="admin_debit"),
                InlineKeyboardButton(text="💰 کیف پول من", callback_data="admin_self_wallet"),
            ],
        ]
    )


def _ensure_tg_user(tg_id: int, username: str | None):
    with SF() as session:
        user = create_or_get_user(session, tg_id, username, settings.currency)
        wallet = ensure_wallet(session, user, settings.currency)
        session.commit()
        return user.id, wallet.id, wallet.balance


def _admin_required(user_id: int | None) -> None:
    if not is_admin(user_id):
        raise PermissionError("admin_required")


def _find_user_and_wallet(session, telegram_id: int):
    user = session.scalar(select(User).where(User.telegram_id == telegram_id))
    if not user:
        return None, None
    wallet = ensure_wallet(session, user, settings.currency)
    return user, wallet


async def start(message: Message):
    _ensure_tg_user(message.from_user.id, message.from_user.username)
    text = "به ربات مرجع 2-id خوش آمدید."
    if is_admin(message.from_user.id):
        text += "\n\n✅ دسترسی مدیریت برای حساب شما فعال است."
    await message.answer(text, reply_markup=main_keyboard(message.from_user.id))


async def wallet(message: Message):
    _, wallet_id, _ = _ensure_tg_user(message.from_user.id, message.from_user.username)
    with SF() as session:
        w = session.get(Wallet, wallet_id)
        await message.answer(f"موجودی: {w.balance:,} {w.currency}")


async def orders(message: Message):
    user_id, _, _ = _ensure_tg_user(message.from_user.id, message.from_user.username)
    with SF() as session:
        rows = session.scalars(
            select(Order).where(Order.user_id == user_id).order_by(Order.created_at.desc()).limit(10)
        ).all()
    if not rows:
        await message.answer("هنوز سفارشی ندارید.")
        return
    await message.answer("\n".join(f"{o.id[:8]} | {o.email_masked} | {o.status}" for o in rows))


async def support(message: Message):
    await message.answer(settings.support_text)


async def begin_create(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(CreateFlow.email)
    await message.answer("ایمیل شخصی را وارد کنید:")


async def get_email(message: Message, state: FSMContext):
    if "@" not in (message.text or ""):
        await message.answer("ایمیل معتبر وارد کنید.")
        return
    await state.update_data(email=message.text.strip())
    await state.set_state(CreateFlow.password)
    await message.answer("پسورد Apple Account را وارد کنید. پیام پسورد بعد از دریافت حذف می‌شود:")


async def get_password(message: Message, state: FSMContext):
    pwd = message.text or ""
    if len(pwd) < 8:
        await message.answer("پسورد باید حداقل ۸ کاراکتر باشد.")
        return
    await state.update_data(password=pwd)
    try:
        await message.delete()
    except Exception:
        pass
    await state.set_state(CreateFlow.first_name)
    await message.answer("نام را وارد کنید:")


async def get_first_name(message: Message, state: FSMContext):
    await state.update_data(first_name=(message.text or "").strip())
    await state.set_state(CreateFlow.last_name)
    await message.answer("نام خانوادگی را وارد کنید:")


async def get_last_name(message: Message, state: FSMContext):
    await state.update_data(last_name=(message.text or "").strip())
    data = await state.get_data()
    await state.set_state(CreateFlow.confirm)
    summary = (
        f"ایمیل: {data['email']}\n"
        f"نام: {data['first_name']} {data['last_name']}\n"
        f"قیمت: {settings.apple_account_price:,} {settings.currency}\n"
        "پسورد نمایش داده نمی‌شود."
    )
    await message.answer(summary, reply_markup=confirm_keyboard())


async def confirm(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id, wallet_id, _ = _ensure_tg_user(callback.from_user.id, callback.from_user.username)
    idem = f"tg:{callback.from_user.id}:{callback.message.message_id}"
    with SF() as session:
        try:
            order = create_apple_order(
                session,
                owner_type="telegram",
                owner_id=str(callback.from_user.id),
                user_id=user_id,
                partner_id=None,
                wallet_id=wallet_id,
                request={k: data[k] for k in ("email", "password", "first_name", "last_name")},
                idempotency_key=idem,
                price=settings.apple_account_price,
                currency=settings.currency,
                crypto=crypto,
                fingerprint_key=settings.partner_key_pepper,
            )
            session.commit()
            msg = f"✅ سفارش ثبت شد: {order.id[:8]}"
        except InsufficientBalance:
            session.rollback()
            msg = "❌ موجودی کیف پول کافی نیست."
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(msg, reply_markup=main_keyboard(callback.from_user.id))
    await callback.answer()


async def cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("سفارش لغو شد.", reply_markup=main_keyboard(callback.from_user.id))
    await callback.answer()


async def admin_menu(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("دسترسی مدیریت ندارید.")
        return
    await message.answer("🛠 پنل مدیریت 2-id", reply_markup=admin_keyboard())


async def admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("دسترسی ندارید.", show_alert=True)
        return
    with SF() as session:
        users_count = session.scalar(select(func.count()).select_from(User)) or 0
        orders_count = session.scalar(select(func.count()).select_from(Order)) or 0
        pending_count = session.scalar(select(func.count()).select_from(Order).where(Order.status.in_(["PENDING", "PROCESSING"]))) or 0
        wallet_total = session.scalar(select(func.coalesce(func.sum(Wallet.balance), 0))) or 0
    text = (
        "📊 آمار سیستم\n\n"
        f"👥 کاربران: {users_count}\n"
        f"📦 کل سفارش‌ها: {orders_count}\n"
        f"⏳ درحال پردازش: {pending_count}\n"
        f"💰 مجموع موجودی کیف پول‌ها: {wallet_total:,} {settings.currency}\n"
        f"💵 قیمت فعلی: {settings.apple_account_price:,} {settings.currency}"
    )
    await callback.message.answer(text, reply_markup=admin_keyboard())
    await callback.answer()


async def admin_users(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("دسترسی ندارید.", show_alert=True)
        return
    with SF() as session:
        rows = session.execute(
            select(User.telegram_id, User.username, Wallet.balance, Wallet.currency)
            .join(Wallet, Wallet.user_id == User.id)
            .order_by(User.created_at.desc())
            .limit(30)
        ).all()
    if not rows:
        text = "کاربری ثبت نشده است."
    else:
        lines = ["👥 آخرین کاربران:"]
        for telegram_id, username, balance, currency in rows:
            name = f"@{username}" if username else "بدون یوزرنیم"
            admin_mark = " 👑" if is_admin(telegram_id) else ""
            lines.append(f"{telegram_id} | {name}{admin_mark} | {balance:,} {currency}")
        text = "\n".join(lines)
    await callback.message.answer(text, reply_markup=admin_keyboard())
    await callback.answer()


async def admin_orders(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("دسترسی ندارید.", show_alert=True)
        return
    with SF() as session:
        rows = session.execute(
            select(Order.id, Order.owner_type, Order.owner_id, Order.email_masked, Order.status, Order.price, Order.refunded)
            .order_by(Order.created_at.desc())
            .limit(30)
        ).all()
    if not rows:
        text = "هنوز سفارشی ثبت نشده است."
    else:
        lines = ["📦 آخرین سفارش‌ها:"]
        for oid, owner_type, owner_id, email, status, price, refunded in rows:
            refund = " | refund" if refunded else ""
            lines.append(f"{oid[:8]} | {owner_type}:{owner_id} | {email} | {status} | {price:,}{refund}")
        text = "\n".join(lines)
    await callback.message.answer(text, reply_markup=admin_keyboard())
    await callback.answer()


async def admin_self_wallet(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("دسترسی ندارید.", show_alert=True)
        return
    _, wallet_id, _ = _ensure_tg_user(callback.from_user.id, callback.from_user.username)
    with SF() as session:
        wallet = session.get(Wallet, wallet_id)
        rows = session.scalars(
            select(LedgerEntry)
            .where(LedgerEntry.wallet_id == wallet.id)
            .order_by(LedgerEntry.created_at.desc())
            .limit(10)
        ).all()
        lines = [f"💰 کیف پول شما: {wallet.balance:,} {wallet.currency}"]
        for entry in rows:
            lines.append(f"{entry.kind}: {entry.amount:+,}")
    await callback.message.answer("\n".join(lines), reply_markup=admin_keyboard())
    await callback.answer()


async def admin_credit(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("دسترسی ندارید.", show_alert=True)
        return
    await state.clear()
    await state.update_data(admin_adjust_sign=1)
    await state.set_state(AdminAdjustFlow.target_user)
    await callback.message.answer("Telegram ID کاربر را برای شارژ وارد کنید:")
    await callback.answer()


async def admin_debit(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("دسترسی ندارید.", show_alert=True)
        return
    await state.clear()
    await state.update_data(admin_adjust_sign=-1)
    await state.set_state(AdminAdjustFlow.target_user)
    await callback.message.answer("Telegram ID کاربر را برای کسر موجودی وارد کنید:")
    await callback.answer()


async def admin_adjust_target(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    try:
        telegram_id = int((message.text or "").strip())
    except ValueError:
        await message.answer("Telegram ID باید عدد باشد.")
        return
    with SF() as session:
        user, wallet = _find_user_and_wallet(session, telegram_id)
        if not user:
            await message.answer("کاربر پیدا نشد. ابتدا کاربر باید یک‌بار /start بزند.")
            return
        username = f"@{user.username}" if user.username else "بدون یوزرنیم"
        balance = wallet.balance
    await state.update_data(admin_target_id=telegram_id)
    await state.set_state(AdminAdjustFlow.amount)
    await message.answer(
        f"کاربر: {telegram_id} | {username}\n"
        f"موجودی فعلی: {balance:,} {settings.currency}\n"
        "مبلغ را به‌صورت عدد صحیح وارد کنید:"
    )


async def admin_adjust_amount(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    try:
        raw_amount = int((message.text or "").replace(",", "").strip())
    except ValueError:
        await message.answer("مبلغ باید عدد صحیح باشد.")
        return
    if raw_amount <= 0:
        await message.answer("مبلغ باید بزرگ‌تر از صفر باشد.")
        return
    target_id = int(data["admin_target_id"])
    sign = int(data["admin_adjust_sign"])
    amount = raw_amount * sign
    with SF() as session:
        user, wallet = _find_user_and_wallet(session, target_id)
        if not user or not wallet:
            await state.clear()
            await message.answer("کاربر دیگر وجود ندارد.")
            return
        try:
            entry = adjust_wallet(
                session,
                wallet.id,
                amount,
                "ADMIN_ADJUSTMENT",
                f"tg-admin:{message.from_user.id}:{target_id}:{time.time_ns()}",
                reference=f"admin:{message.from_user.id}",
            )
        except InsufficientBalance:
            session.rollback()
            await message.answer("❌ موجودی کاربر برای این مقدار کسر کافی نیست.")
            return
        session.add(
            AuditLog(
                actor=f"telegram-admin:{message.from_user.id}",
                action="wallet.adjust",
                target=user.id,
                detail=f"{amount:+d}",
            )
        )
        session.commit()
        balance = wallet.balance
        entry_id = entry.id
    await state.clear()
    action = "شارژ" if amount > 0 else "کسر"
    await message.answer(
        f"✅ {action} انجام شد.\n"
        f"Telegram ID: {target_id}\n"
        f"مبلغ: {amount:+,} {settings.currency}\n"
        f"موجودی جدید: {balance:,} {settings.currency}\n"
        f"Ledger: {entry_id[:8]}",
        reply_markup=main_keyboard(message.from_user.id),
    )


async def begin_email_otp(message: Message, state: FSMContext):
    user_id, _, _ = _ensure_tg_user(message.from_user.id, message.from_user.username)
    with SF() as session:
        pending = session.scalars(
            select(Order)
            .where(Order.user_id == user_id, Order.status == "EMAIL_OTP_REQUIRED")
            .order_by(Order.created_at.desc())
            .limit(5)
        ).all()
    if not pending:
        await message.answer("هیچ سفارشی منتظر کد تأیید ایمیل نیست.")
        return
    await state.clear()
    if len(pending) == 1:
        await state.update_data(email_otp_order_id=pending[0].id)
        await state.set_state(EmailOtpFlow.otp)
        await message.answer(
            f"کد تأیید ایمیل سفارش {pending[0].id[:8]} را وارد کنید. "
            "کد فقط یک‌بار و به‌صورت رمز‌شده نگهداری می‌شود:"
        )
        return
    await state.set_state(EmailOtpFlow.order_id)
    lines = ["چند سفارش منتظر کد هستند. ۸ کاراکتر اول شناسه سفارش را بفرستید:"]
    lines.extend(f"{o.id[:8]} | {o.email_masked}" for o in pending)
    await message.answer("\n".join(lines))


async def email_otp_select_order(message: Message, state: FSMContext):
    user_id, _, _ = _ensure_tg_user(message.from_user.id, message.from_user.username)
    prefix = (message.text or "").strip().lower()
    if len(prefix) < 6:
        await message.answer("شناسه سفارش معتبر نیست.")
        return
    with SF() as session:
        rows = session.scalars(
            select(Order).where(Order.user_id == user_id, Order.status == "EMAIL_OTP_REQUIRED")
        ).all()
    matches = [o for o in rows if o.id.lower().startswith(prefix)]
    if len(matches) != 1:
        await message.answer("سفارش پیدا نشد یا شناسه مبهم است.")
        return
    await state.update_data(email_otp_order_id=matches[0].id)
    await state.set_state(EmailOtpFlow.otp)
    await message.answer("کد تأیید ایمیل را وارد کنید:")


async def email_otp_submit(message: Message, state: FSMContext):
    user_id, _, _ = _ensure_tg_user(message.from_user.id, message.from_user.username)
    value = (message.text or "").strip().replace(" ", "")
    if not value.isdigit() or not (4 <= len(value) <= 8):
        await message.answer("کد باید ۴ تا ۸ رقم باشد.")
        return
    data = await state.get_data()
    order_id = data.get("email_otp_order_id")
    with SF() as session:
        order = session.scalar(
            select(Order).where(
                Order.id == order_id,
                Order.user_id == user_id,
                Order.status == "EMAIL_OTP_REQUIRED",
            )
        )
        if not order:
            await state.clear()
            await message.answer("این سفارش دیگر منتظر کد ایمیل نیست.")
            return
        job = session.scalar(select(AppleJob).where(AppleJob.order_id == order.id))
        challenge = session.scalar(select(AppleChallenge).where(AppleChallenge.job_id == job.id))
        if not challenge or challenge.kind != "email_otp":
            await state.clear()
            await message.answer("درخواست کد برای این سفارش معتبر نیست.")
            return
        if challenge.expires_at and challenge.expires_at < now_utc():
            await state.clear()
            await message.answer("مهلت این کد تمام شده است؛ Worker باید درخواست جدید ایجاد کند.")
            return
        challenge.encrypted_value = crypto.encrypt({"value": value})
        challenge.consumed_at = None
        session.add(
            AuditLog(
                actor=f"telegram-user:{message.from_user.id}",
                action="apple.email_otp.submit",
                target=order.id,
                detail="encrypted",
            )
        )
        session.commit()
    try:
        await message.delete()
    except Exception:
        pass
    await state.clear()
    await message.answer(
        "✅ کد ایمیل رمزگذاری و برای Worker ارسال شد. خود کد در تاریخچه سفارش نمایش داده نمی‌شود.",
        reply_markup=main_keyboard(message.from_user.id),
    )


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.message.register(start, CommandStart())
    dp.message.register(admin_menu, Command("admin"))
    dp.message.register(begin_create, F.text == "🍎 ساخت Apple ID")
    dp.message.register(wallet, F.text == "💰 کیف پول")
    dp.message.register(orders, F.text == "📦 سفارش‌های من")
    dp.message.register(support, F.text == "🛟 پشتیبانی")
    dp.message.register(begin_email_otp, F.text == "📧 ثبت کد ایمیل")
    dp.message.register(admin_menu, F.text == "🛠 مدیریت")
    dp.message.register(get_email, CreateFlow.email)
    dp.message.register(get_password, CreateFlow.password)
    dp.message.register(get_first_name, CreateFlow.first_name)
    dp.message.register(get_last_name, CreateFlow.last_name)
    dp.message.register(admin_adjust_target, AdminAdjustFlow.target_user)
    dp.message.register(admin_adjust_amount, AdminAdjustFlow.amount)
    dp.message.register(email_otp_select_order, EmailOtpFlow.order_id)
    dp.message.register(email_otp_submit, EmailOtpFlow.otp)
    dp.callback_query.register(confirm, F.data == "order_confirm", CreateFlow.confirm)
    dp.callback_query.register(cancel, F.data == "order_cancel")
    dp.callback_query.register(admin_stats, F.data == "admin_stats")
    dp.callback_query.register(admin_users, F.data == "admin_users")
    dp.callback_query.register(admin_orders, F.data == "admin_orders")
    dp.callback_query.register(admin_credit, F.data == "admin_credit")
    dp.callback_query.register(admin_debit, F.data == "admin_debit")
    dp.callback_query.register(admin_self_wallet, F.data == "admin_self_wallet")
    return dp


async def _main():
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
    bot = Bot(settings.telegram_bot_token)
    await build_dispatcher().start_polling(bot)


def main():
    configure_logging()
    asyncio.run(_main())


if __name__ == "__main__":
    main()
