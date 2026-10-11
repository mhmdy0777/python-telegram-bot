
"""Telegram handlers for ELITA Finance."""

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
    ("start", "Open ELITA Finance"),
    ("help", "Show commands"),
    ("about", "About the bot"),
    ("ping", "Check bot status"),
    ("expense", "Record an expense"),
    ("income", "Record incoming money"),
    ("balance", "Show account balances"),
    ("report", "Show monthly report"),
)

MENU_HELP = "Help"
MENU_ABOUT = "About"
MENU_PING = "Ping"

MAIN_MENU_KEYBOARD = ReplyKeyboardMarkup(
    [[MENU_HELP, MENU_ABOUT], [MENU_PING]],
    resize_keyboard=True,
    is_persistent=True,
)

HELP_TEXT = """ELITA Finance — expense tracking

Commands:
/expense company 90000 gas
/expense personal 150000 fuel
/income company 3000000 advance
/balance
/report
/help

Amounts are entered in Uzbek soums.
Use company for company accountable funds
and personal for personal money.

Example:
/expense company 90000 gas methane
"""


def get_pool(context: ContextTypes.DEFAULT_TYPE):
    return context.bot_data.get(DB_KEY)


def account_label(account: str) -> str:
    return "Company" if account == "company" else "Personal"


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
        "Welcome to ELITA Finance!\n\n" + HELP_TEXT,
        reply_markup=MAIN_MENU_KEYBOARD,
    )


async def help_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    del context
    if update.effective_message:
        await update.effective_message.reply_text(HELP_TEXT)


async def about(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    del context
    if update.effective_message:
        await update.effective_message.reply_text(
            "ELITA Finance tracks company and personal income and expenses."
        )


async def ping(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.effective_message
    if message is None:
        return

    client = context.bot_data.get(REDIS_KEY)
    if client is None:
        await message.reply_text("Bot is running.")
        return

    cached = await cache.get_or_set_ping(client)
    await message.reply_text(
        "Bot is running." if cached else "Bot is running (fresh check)."
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
        await message.reply_text(
            "Database is unavailable. Please try again later."
        )
        return

    args = context.args
    if len(args) < 3:
        command = "expense" if transaction_type == "expense" else "income"
        await message.reply_text(
            f"Format: /{command} company 90000 category description\n"
            f"Or: /{command} personal 90000 category description"
        )
        return

    account_type = args[0].lower()

    if account_type not in ("company", "personal"):
        await message.reply_text(
            "Account must be company or personal."
        )
        return

    try:
        amount = int(args[1].replace(",", "").replace("_", ""))
    except ValueError:
        await message.reply_text(
            "Amount must be a whole number, e.g. 90000."
        )
        return

    if amount <= 0:
        await message.reply_text("Amount must be greater than zero.")
        return

    category = args[2].strip()
    description = " ".join(args[3:]).strip()

    transaction_id = await db.add_transaction(
        pool=pool,
        telegram_id=user.id,
        account_type=account_type,
        transaction_type=transaction_type,
        amount=amount,
        category=category,
        description=description,
    )

    kind = "Expense recorded" if transaction_type == "expense" else "Income recorded"
    balance = await db.get_balance(pool, user.id, account_type)

    await message.reply_text(
        f"{kind} successfully.\n"
        f"Account: {account_label(account_type)}\n"
        f"Amount: {amount:,} UZS\n"
        f"Category: {category}\n"
        f"Description: {description or '-'}\n"
        f"Current balance: {balance:,} UZS\n"
        f"Operation ID: {transaction_id}"
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
        await message.reply_text("Database is unavailable.")
        return

    company = await db.get_balance(pool, user.id, "company")
    personal = await db.get_balance(pool, user.id, "personal")

    await message.reply_text(
        "BALANCE\n\n"
        f"Company: {company:,} UZS\n"
        f"Personal: {personal:,} UZS"
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
        await message.reply_text("Database is unavailable.")
        return

    rows = await db.get_report(pool, user.id)
    if not rows:
        await message.reply_text(
            "No transactions recorded this month."
        )
        return

    lines = ["MONTHLY REPORT"]
    for row in rows:
        account = account_label(row["account_type"])
        kind = (
            "Expense"
            if row["transaction_type"] == "expense"
            else "Income"
        )
        lines.append(
            f"{account} | {kind} | {row['category']}: "
            f"{row['total']:,} UZS ({row['operations']} operations)"
        )

    await message.reply_text("\n".join(lines))


async def menu_button(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.effective_message
    if message is None or not message.text:
        return

    if message.text.strip() == MENU_HELP:
        await help_command(update, context)
    elif message.text.strip() == MENU_ABOUT:
        await about(update, context)
    elif message.text.strip() == MENU_PING:
        await ping(update, context)


async def text_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(
            "To record an expense, use a command such as:\n"
            "/expense company 90000 gas\n\n"
            "For balances, send /balance.\n"
            "For the monthly report, send /report."
        )


async def unknown_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    del context
    if update.effective_message:
        await update.effective_message.reply_text(
            "Unknown command. Type /help."
        )


async def error_handler(
    update: object, context: ContextTypes.DEFAULT_TYPE
) -> None:
    error = context.error

    if isinstance(error, (Conflict, NetworkError, TimedOut)):
        logger.warning("Transient Telegram error: %s", error)
        return

    logger.exception(
        "Error while processing update: %s",
        update,
        exc_info=error,
    )

    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "An error occurred. Please try again."
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
    application.add_handler(
        MessageHandler(filters.COMMAND, unknown_command)
    )
    application.add_handler(
        MessageHandler(
            filters.Regex(f"^({MENU_HELP}|{MENU_ABOUT}|{MENU_PING})$"),
            menu_button,
        )
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_message)
    )
