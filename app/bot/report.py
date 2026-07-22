"""Диалог сдачи отчёта: /report — объект, работы, численность, подтверждение, запись."""

from datetime import date, datetime

import structlog
from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import ConstructionSite, DailyReport, User, site_assignments
from app.models.base import PG_INT_MAX


class ReportDialog(StatesGroup):
    """Шаги диалога; ответы копятся в FSM и пишутся одной транзакцией на «Отправить»."""

    choosing_site = State()
    entering_description = State()
    entering_workers = State()
    confirming = State()


_SITE_PREFIX = "report_site:"
_SUBMIT = "report:submit"
_RESTART = "report:restart"
_CANCEL = "report:cancel"

log = structlog.get_logger()


def create_router() -> Router:
    router = Router()
    router.message.register(cmd_report, Command("report"))
    router.message.register(cmd_cancel, Command("cancel"))
    router.message.register(description_entered, StateFilter(ReportDialog.entering_description))
    router.message.register(workers_entered, StateFilter(ReportDialog.entering_workers))
    router.callback_query.register(
        site_chosen, StateFilter(ReportDialog.choosing_site), F.data.startswith(_SITE_PREFIX)
    )
    confirming = StateFilter(ReportDialog.confirming)
    router.callback_query.register(submitted, confirming, F.data == _SUBMIT)
    router.callback_query.register(restarted, confirming, F.data == _RESTART)
    # StateFilter(ReportDialog): «Отмена» вне диалога — устаревшая кнопка, а не отмена
    router.callback_query.register(cancelled, StateFilter(ReportDialog), F.data == _CANCEL)
    # последним: кнопки завершённых диалогов (после рестарта бота MemoryStorage пуст)
    router.callback_query.register(stale_callback)
    return router


def _today() -> date:
    # «сегодня» в поясе компании: вечерний отчёт по UTC-дате уехал бы на другой день
    return datetime.now(get_settings().company_tzinfo).date()


async def _assigned_sites(session: AsyncSession, foreman: User) -> list[ConstructionSite]:
    return list(
        await session.scalars(
            select(ConstructionSite)
            .join(site_assignments)
            .where(site_assignments.c.user_id == foreman.id)
            .order_by(ConstructionSite.id)
        )
    )


def _sites_keyboard(sites: list[ConstructionSite]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=site.name, callback_data=f"{_SITE_PREFIX}{site.id}")]
        for site in sites
    ]
    rows.append([InlineKeyboardButton(text="Отмена", callback_data=_CANCEL)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отправить", callback_data=_SUBMIT)],
            [InlineKeyboardButton(text="Начать заново", callback_data=_RESTART)],
            [InlineKeyboardButton(text="Отмена", callback_data=_CANCEL)],
        ]
    )


async def _start_dialog(
    message: Message, state: FSMContext, session: AsyncSession, foreman: User
) -> None:
    sites = await _assigned_sites(session, foreman)
    if not sites:
        await message.answer("Вам не назначен ни один объект — сдавать отчёты пока не за что.")
        return
    await state.set_state(ReportDialog.choosing_site)
    await message.answer("За какой объект отчёт?", reply_markup=_sites_keyboard(sites))


async def cmd_report(
    message: Message, state: FSMContext, session: AsyncSession, foreman: User
) -> None:
    """Начало диалога; незаконченный предыдущий диалог отбрасывается."""
    await state.clear()
    await _start_dialog(message, state, session, foreman)


async def cmd_cancel(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        await message.answer("Сейчас ничего не заполняется.")
        return
    await state.clear()
    await message.answer("Сдача отчёта отменена.")


async def site_chosen(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, foreman: User
) -> None:
    raw_id = callback.data.removeprefix(_SITE_PREFIX)
    # кнопкам не доверяем: callback_data мог подделать клиент — мусор вместо id,
    # переполнение int32 и чужой объект получают один и тот же отказ
    valid_id = raw_id.isdecimal() and int(raw_id) <= PG_INT_MAX
    site = await _get_assigned_site(session, foreman, int(raw_id)) if valid_id else None
    if site is None:
        await callback.answer("Объект вам не назначен")
        return
    already_reported = await session.scalar(
        select(DailyReport.id).where(
            DailyReport.site_id == site.id,
            DailyReport.foreman_id == foreman.id,
            DailyReport.report_date == _today(),
        )
    )
    await state.update_data(site_id=site.id, site_name=site.name)
    await state.set_state(ReportDialog.entering_description)
    warning = (
        "За сегодня по этому объекту уже есть отчёт — новый заменит его.\n"
        if already_reported
        else ""
    )
    await callback.message.answer(f"{warning}Что сделали за день?")
    await callback.answer()


async def description_entered(message: Message, state: FSMContext) -> None:
    description = (message.text or "").strip()
    if not description:
        await message.answer("Опишите работы текстом.")
        return
    await state.update_data(work_description=description)
    await state.set_state(ReportDialog.entering_workers)
    await message.answer("Сколько рабочих было на объекте?")


async def workers_entered(message: Message, state: FSMContext) -> None:
    try:
        workers = int((message.text or "").strip())
    except ValueError:
        await message.answer("Введите число рабочих цифрами, например: 8")
        return
    if not 0 <= workers <= PG_INT_MAX:
        await message.answer("Число рабочих не может быть отрицательным или таким большим.")
        return
    data = await state.update_data(workers_count=workers)
    await state.set_state(ReportDialog.confirming)
    summary = (
        f"Проверьте отчёт:\n"
        f"Объект: {data['site_name']}\n"
        f"Дата: {_today():%d.%m.%Y}\n"
        f"Работы: {data['work_description']}\n"
        f"Рабочих: {data['workers_count']}"
    )
    await message.answer(summary, reply_markup=_confirm_keyboard())


async def submitted(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, foreman: User
) -> None:
    """Единственная точка записи: отчёт целиком уходит в БД одной транзакцией."""
    data = await state.get_data()
    site = await _get_assigned_site(session, foreman, data["site_id"])
    if site is None:
        # назначение сняли, пока прораб заполнял отчёт
        log.info(
            "report_rejected",
            reason="site_unassigned",
            site_id=data["site_id"],
            foreman_id=foreman.id,
        )
        await state.clear()
        await callback.message.answer("Объект вам больше не назначен — отчёт не сохранён.")
        await callback.answer()
        return
    report_date = _today()
    # свой отчёт за сегодня заменяется: прораб предупреждён при выборе объекта,
    # детали старого отчёта удаляет каскад в БД
    deleted = await session.execute(
        delete(DailyReport).where(
            DailyReport.site_id == site.id,
            DailyReport.foreman_id == foreman.id,
            DailyReport.report_date == report_date,
        )
    )
    session.add(
        DailyReport(
            site_id=site.id,
            foreman_id=foreman.id,
            report_date=report_date,
            work_description=data["work_description"],
            workers_count=data["workers_count"],
            photos=[],
            material_usages=[],
        )
    )
    try:
        await session.commit()
    except IntegrityError:
        # гонка с офисом: объект удалили между проверкой и записью
        log.warning(
            "report_rejected", reason="site_deleted", site_id=site.id, foreman_id=foreman.id
        )
        await state.clear()
        await callback.message.answer("Объект уже удалён — отчёт не сохранён.")
        await callback.answer()
        return
    log.info(
        "report_accepted",
        site_id=site.id,
        foreman_id=foreman.id,
        report_date=report_date.isoformat(),
        replaced=deleted.rowcount > 0,
    )
    await state.clear()
    await callback.message.answer(f"Отчёт принят: {site.name}, {report_date:%d.%m.%Y}.")
    await callback.answer()


async def restarted(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, foreman: User
) -> None:
    await state.clear()
    await _start_dialog(callback.message, state, session, foreman)
    await callback.answer()


async def cancelled(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("Сдача отчёта отменена.")
    await callback.answer()


async def stale_callback(callback: CallbackQuery) -> None:
    await callback.answer("Кнопка устарела — начните заново: /report", show_alert=True)


async def _get_assigned_site(
    session: AsyncSession, foreman: User, site_id: int
) -> ConstructionSite | None:
    return await session.scalar(
        select(ConstructionSite)
        .join(site_assignments)
        .where(ConstructionSite.id == site_id, site_assignments.c.user_id == foreman.id)
    )
