from __future__ import annotations

import asyncio
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from sqlalchemy import select

from .config import get_settings
from .crypto import PayloadCrypto
from .db import make_engine, make_session_factory
from .logging import configure_logging
from .models import Order, Wallet
from .orders import create_apple_order, create_or_get_user
from .wallet import InsufficientBalance, ensure_wallet

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


def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🍎 ساخت Apple ID"), KeyboardButton(text="💰 کیف پول")],
            [KeyboardButton(text="📦 سفارش‌های من"), KeyboardButton(text="🛟 پشتیبانی")],
        ],
        resize_keyboard=True,
    )


def confirm_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ ثبت سفارش", callback_data="order_confirm"),
                InlineKeyboardButton(text="❌ لغو", callback_data="order_cancel"),
            ]
        ]
    )


def _ensure_tg_user(tg_id: int, username: str | None):
    with SF() as session:
        user = create_or_get_user(session, tg_id, username, settings.currency)
        wallet = ensure_wallet(session, user, settings.currency)
        session.commit()
        return user.id, wallet.id, wallet.balance


async def start(message: Message):
    _ensure_tg_user(message.from_user.id, message.from_user.username)
    await message.answer("به ربات مرجع 2-id خوش آمدید.", reply_markup=main_keyboard())


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
    await callback.message.answer(msg, reply_markup=main_keyboard())
    await callback.answer()


async def cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("سفارش لغو شد.", reply_markup=main_keyboard())
    await callback.answer()


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.message.register(start, CommandStart())
    dp.message.register(begin_create, F.text == "🍎 ساخت Apple ID")
    dp.message.register(wallet, F.text == "💰 کیف پول")
    dp.message.register(orders, F.text == "📦 سفارش‌های من")
    dp.message.register(support, F.text == "🛟 پشتیبانی")
    dp.message.register(get_email, CreateFlow.email)
    dp.message.register(get_password, CreateFlow.password)
    dp.message.register(get_first_name, CreateFlow.first_name)
    dp.message.register(get_last_name, CreateFlow.last_name)
    dp.callback_query.register(confirm, F.data == "order_confirm", CreateFlow.confirm)
    dp.callback_query.register(cancel, F.data == "order_cancel")
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
