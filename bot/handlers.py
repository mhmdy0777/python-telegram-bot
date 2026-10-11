
"""Handlers for ELITA Finance."""

import logging
import re

from telegram import ReplyKeyboardMarkup, Update
from telegram.error import Conflict, NetworkError, TimedOut
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot import cache, db

logger = logging.getLogger(__name__)

DB_KEY = "db"
REDIS_KEY = "redis"

BOT_COMMANDS = (
    ("start", "Главное меню"),
    ("expense", "Записать расход"),
    ("income", "Записать приход"),
    ("balance", "Показать баланс"),
    ("report", "Отчёт за месяц"),
)

MENU_EXPENSE = "💸 Расход"
MENU_INCOME = "💰 Приход"
MENU_BALANCE = "💳 Баланс"
MENU_REPORT = "📊 Отчёт за месяц"
MENU_ACCOUNTABLE = "🧾 Подотчёт"

MAIN_MENU_KEYBOARD = ReplyKeyboardMarkup(
    [
        [MENU_EXPENSE, MENU_INCOME],
        [MENU_BALANCE, MENU_REPORT],
        [MENU_ACCOUNTABLE],
    ],
    resize_keyboard=True,
    is_persistent=True,
)

HELP_TEXT = (
    "Добро пожаловать в ELITA Finance! 👋\n\n"
    "Выбери нужный раздел кнопками ниже.\n\n"
    "Примеры операций:\n"
    "Расход компании 90 000 сум на газ\n"
    "Компания получила 3 000 000 сум\n"
    "Личные расходы 50 000 сум на бензин\n\n"
    "Все суммы указывай в сумах."
)


def get_pool(context: ContextTypes.DEFAULT_TYPE):
    return context.bot_data.get(DB_KEY)


def account_label(account: str) -> str:
    return {
        "company": "Компания",
        "personal": "Личные деньги",
        "accountable": "Подотчёт",
    }.get(account, account)


async def start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.effective_message
    user = update.effective_user

    if message is None or user is None:
        return

    pool = get_pool(context)
    if pool is not None:
        await db.upsert_user(
            pool, user.id, user.username, user.first_name
        )

    await message.reply_text(
        HELP_TEXT,
        reply_markup=MAIN_MENU_KEYBOARD,
    )


async def help_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    del context
    if update.effective_message:
        await update.effective_message.reply_text(
            HELP_TEXT,
            reply_markup=MAIN_MENU_KEYBOARD,
        )


async def about(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    del context
    if update.effective_message:
        await update.effective_message.reply_text(
            "ELITA Finance — учёт расходов, поступлений "
            "и денежных остатков."
        )


async def ping(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.effective_message
    if message is None:
        return

    client = context.bot_data.get(REDIS_KEY)
    if client is None:
        await message.reply_text("Бот работает.")
        return

    cached = await cache.get_or_set_ping(client)
    await message.reply_text(
        "Бот работает." if cached
        else "Бот работает. Проверка выполнена."
    )


async def record_transaction(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    transaction_type: str,
) -> None:
    message = update.effective_message
    user = update.effective_user

    if message is None or user is None:
        return

    pool = get_pool(context)
    if pool is None:
        await message.reply_text("База данных недоступна.")
        return

    args = context.args
    if len(args) < 3:
        command = (
            "expense" if transaction_type == "expense"
            else "income"
        )
        await message.reply_text(
            f"Формат: /{command} company 90000 gas описание\n"
            f"Или: /{command} personal 50000 fuel описание\n"
            f"Счёт подотчёта: accountable"
        )
        return

    account_type = args[0].lower()
    if account_type not in (
        "company", "personal", "accountable"
    ):
        await message.reply_text(
            "Счёт: company, personal или accountable."
        )
        return

    try:
        amount = int(
            args[1].replace(",", "").replace("_", "")
        )
    except ValueError:
        await message.reply_text(
            "Укажи сумму целым числом, например 90000."
        )
        return

    if amount <= 0:
        await message.reply_text(
            "Сумма должна быть больше нуля."
        )
        return

    category = args[2].strip()
    description = " ".join(args[3:]).strip()

    operation_id = await db.add_transaction(
        pool=pool,
        telegram_id=user.id,
        account_type=account_type,
        transaction_type=transaction_type,
        amount=amount,
        category=category,
        description=description,
    )

    balance_value = await db.get_balance(
        pool, user.id, account_type
    )

    kind = (
        "Расход записан"
        if transaction_type == "expense"
        else "Приход записан"
    )

    await message.reply_text(
        f"{kind}.\n"
        f"Счёт: {account_label(account_type)}\n"
        f"Сумма: {amount:,} сум\n"
        f"Категория: {category}\n"
        f"Описание: {description or '-'}\n"
        f"Баланс счёта: {balance_value:,} сум\n"
        f"Номер операции: {operation_id}",
        reply_markup=MAIN_MENU_KEYBOARD,
    )


async def expense(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await record_transaction(update, context, "expense")


async def income(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await record_transaction(update, context, "income")


async def balance(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.effective_message
    user = update.effective_user

    if message is None or user is None:
        return

    pool = get_pool(context)
    if pool is None:
        await message.reply_text("База данных недоступна.")
        return

    company = await db.get_balance(
        pool, user.id, "company"
    )
    personal = await db.get_balance(
        pool, user.id, "personal"
    )
    accountable = await db.get_balance(
        pool, user.id, "accountable"
    )

    await message.reply_text(
        "💳 БАЛАНС\n\n"
        f"Компания: {company:,} сум\n"
        f"Личные деньги: {personal:,} сум\n"
        f"Подотчётный счёт: {accountable:,} сум",
        reply_markup=MAIN_MENU_KEYBOARD,
    )


async def report(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.effective_message
    user = update.effective_user

    if message is None or user is None:
        return

    pool = get_pool(context)
    if pool is None:
        await message.reply_text("База данных недоступна.")
        return

    rows = await db.get_report(pool, user.id)
    if not rows:
        await message.reply_text(
            "За этот месяц операций пока нет.",
            reply_markup=MAIN_MENU_KEYBOARD,
        )
        return

    account_names = {
        "company": "Компания",
        "personal": "Личные деньги",
        "accountable": "Подотчёт",
    }

    category_names = {
        "gas": "Газ",
        "газ": "Газ",
        "бензин": "Бензин",
        "fuel": "Топливо",
        "топливо": "Топливо",
        "repair": "Ремонт",
        "ремонт": "Ремонт",
        "salary": "Зарплата",
        "зарплата": "Зарплата",
        "rent": "Аренда",
        "аренда": "Аренда",
        "other": "Прочее",
        "прочее": "Прочее",
    }

    lines = ["📊 ОТЧЁТ ЗА МЕСЯЦ", ""]
    total_expense = 0
    total_income = 0

    for row in rows:
        account = account_names.get(
            row["account_type"],
            str(row["account_type"]),
        )
        kind = row["transaction_type"]
        amount = int(row["total"])
        category = str(row["category"])
        category = category_names.get(
            category.lower(), category
        )

        if kind == "expense":
            kind_label = "Расход"
            total_expense += amount
        else:
            kind_label = "Приход"
            total_income += amount

        amount_text = f"{amount:,}".replace(",", " ")
        lines.append(
            f"{account} | {kind_label}\n"
            f"  {category}: {amount_text} сум "
            f"(операций: {row['operations']})"
        )

    lines.extend([
        "",
        f"Всего приход: "
        f"{total_income:,}".replace(",", " ") + " сум",
        f"Всего расход: "
        f"{total_expense:,}".replace(",", " ") + " сум",
        f"Разница: "
        f"{total_income - total_expense:,}".replace(",", " ")
        + " сум",
    ])

    await message.reply_text(
        "\n".join(lines),
        reply_markup=MAIN_MENU_KEYBOARD,
    )


async def menu_button(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.effective_message
    if message is None or not message.text:
        return

    text = message.text.strip()

    if text == MENU_BALANCE:
        await balance(update, context)
    elif text == MENU_REPORT:
        await report(update, context)
    elif text == MENU_EXPENSE:
        await message.reply_text(
            "Напиши расход, например:\n"
            "Расход компании 90 000 сум на газ\n"
            "Личные расходы 50 000 сум на бензин"
        )
    elif text == MENU_INCOME:
        await message.reply_text(
            "Напиши поступление, например:\n"
            "Компания получила 3 000 000 сум\n"
            "Получил 500 000 сум личных денег"
        )
    elif text == MENU_ACCOUNTABLE:
        await message.reply_text(
            "🧾 ПОДОТЧЁТ\n\n"
            "Раздел подготовлен для дальнейшей настройки.\n"
            "Выдача под отчёт, расходы и возвраты "
            "пока не реализованы полностью."
        )


async def text_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.effective_message
    user = update.effective_user

    if message is None or not message.text or user is None:
        return

    text = message.text.strip()
    lower = text.lower()

    if any(word in lower for word in (
        "баланс", "остаток денег", "сколько осталось"
    )):
        await balance(update, context)
        return

    if any(word in lower for word in (
        "отчёт", "отчет", "за месяц", "расходы за месяц"
    )):
        await report(update, context)
        return

    match = re.search(r"(?<!\d)\d[\d ,]*(?!\d)", text)
    if not match:
        await message.reply_text(
            "Не нашёл сумму. Пример: "
            "«Расход компании 90 000 сум на газ»."
        )
        return

    amount_text = re.sub(r"[^\d]", "", match.group())
    if not amount_text:
        await message.reply_text("Не удалось определить сумму.")
        return

    amount = int(amount_text)
    if amount <= 0:
        await message.reply_text(
            "Сумма должна быть больше нуля."
        )
        return

    company_words = (
        "компан", "служебн", "учебн", "автомакт",
        "корпоратив", "рабочая машина", "рабочую машину",
    )
    personal_words = (
        "личн", "свои деньги", "мои деньги",
        "личных денег",
    )
    accountable_words = (
        "подотчёт", "подотчет", "из подотчёта",
        "из подотчета",
    )

    is_accountable = any(
        word in lower for word in accountable_words
    )
    is_company = any(word in lower for word in company_words)
    is_personal = any(word in lower for word in personal_words)

    if is_accountable:
        account_type = "accountable"
    elif is_company and is_personal:
        await message.reply_text(
            "Уточни, пожалуйста: компания или личные деньги?"
        )
        return
    elif is_company:
        account_type = "company"
    elif is_personal:
        account_type = "personal"
    else:
        await message.reply_text(
            "Уточни, за какой счёт операция:\n"
            "Напиши «компания», «личные деньги» "
            "или «подотчёт»."
        )
        return

    income_words = (
        "получил", "получила", "выдали", "поступил",
        "поступили", "внес", "внёс", "пополнение",
        "приход", "вернули деньги",
    )
    transaction_type = (
        "income"
        if any(word in lower for word in income_words)
        else "expense"
    )

    categories = {
        "газ": "Газ",
        "метан": "Газ",
        "бензин": "Бензин",
        "топлив": "Топливо",
        "ремонт": "Ремонт",
        "масло": "Масло",
        "аренд": "Аренда",
        "зарплат": "Зарплата",
        "штраф": "Штраф",
        "обед": "Питание",
        "канц": "Канцтовары",
    }

    category = next(
        (
            value for word, value in categories.items()
            if word in lower
        ),
        "Прочее",
    )

    pool = get_pool(context)
    if pool is None:
        await message.reply_text("База данных недоступна.")
        return

    operation_id = await db.add_transaction(
        pool=pool,
        telegram_id=user.id,
        account_type=account_type,
        transaction_type=transaction_type,
        amount=amount,
        category=category,
        description=text,
    )

    current_balance = await db.get_balance(
        pool, user.id, account_type
    )

    operation_name = (
        "Поступление записано"
        if transaction_type == "income"
        else "Расход записан"
    )

    await message.reply_text(
        f"✅ {operation_name}\n"
        f"Счёт: {account_label(account_type)}\n"
        f"Сумма: {amount:,} сум\n"
        f"Категория: {category}\n"
        f"Баланс счёта: {current_balance:,} сум\n"
        f"Номер операции: {operation_id}",
        reply_markup=MAIN_MENU_KEYBOARD,
    )


async def unknown_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    del context
    if update.effective_message:
        await update.effective_message.reply_text(
            "Неизвестная команда. Нажми /start."
        )


async def error_handler(
    update: object, context: ContextTypes.DEFAULT_TYPE
) -> None:
    error = context.error

    if isinstance(error, (Conflict, NetworkError, TimedOut)):
        logger.warning("Временная ошибка Telegram: %s", error)
        return

    logger.exception(
        "Ошибка при обработке сообщения: %s",
        update,
        exc_info=error,
    )

    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "Произошла ошибка. Попробуй ещё раз."
        )


async def set_bot_commands(application: Application) -> None:
    await application.bot.set_my_commands(BOT_COMMANDS)


def register_handlers(application: Application) -> None:
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("about", about))
    application.add_handler(CommandHandler("ping", ping))
    application.add_handler(CommandHandler("expense", expense))
    application.add_handler(CommandHandler("income", income))
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("report", report))

    menu_pattern = (
        r"^(💸 Расход|💰 Приход|💳 Баланс|"
        r"📊 Отчёт за месяц|🧾 Подотчёт)$"
    )

    application.add_handler(
        MessageHandler(
            filters.Regex(menu_pattern),
            menu_button,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.COMMAND,
            unknown_command,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_message,
        )
    )


    
 