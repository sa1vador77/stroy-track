"""Управление пользователями: читает офис, изменяет только админ."""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, PathID, SessionDep, office_only, require_roles
from app.core.security import hash_password
from app.models import User, UserRole
from app.schemas.users import UserCreate, UserOut, UserUpdate

# DELETE нет намеренно: на пользователей ссылаются отчёты (FK RESTRICT),
# увольнение — это деактивация (is_active=false), история отчётов остаётся
router = APIRouter(prefix="/users", tags=["users"])

# чтение (office_only) нужно и менеджеру — выбирать прорабов для назначения на объекты
admin_only = Depends(require_roles(UserRole.ADMIN))


def _conflict_detail(exc: IntegrityError) -> str:
    # имена констрейнтов детерминированы naming convention в metadata
    message = str(exc.orig)
    if "uq_users_email" in message:
        return "email уже занят"
    if "uq_users_telegram_id" in message:
        return "telegram_id уже занят"
    return "конфликт уникальности"


async def _get_user_or_404(session: AsyncSession, user_id: int) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    return user


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[admin_only])
async def create_user(data: UserCreate, session: SessionDep) -> UserOut:
    """Создать пользователя. Пароль нужен только тем, кто входит в API по email."""
    password_hash = await run_in_threadpool(hash_password, data.password) if data.password else None
    user = User(
        full_name=data.full_name,
        role=data.role,
        email=data.email,
        password_hash=password_hash,
        telegram_id=data.telegram_id,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, _conflict_detail(exc)) from None
    return UserOut.model_validate(user)


@router.get("", dependencies=[office_only])
async def list_users(session: SessionDep) -> list[UserOut]:
    """Все пользователи по возрастанию id."""
    users = await session.scalars(select(User).order_by(User.id))
    return [UserOut.model_validate(user) for user in users]


@router.get("/{user_id}", dependencies=[office_only])
async def get_user(user_id: PathID, session: SessionDep) -> UserOut:
    """Пользователь по id; 404 — не найден."""
    return UserOut.model_validate(await _get_user_or_404(session, user_id))


@router.patch("/{user_id}", dependencies=[admin_only])
async def update_user(
    user_id: PathID, data: UserUpdate, session: SessionDep, current: CurrentUser
) -> UserOut:
    """Частичное обновление; свою роль и активность админ менять не может."""
    # объекты пользователя грузим сразу: при смене роли коллекция чистится
    # через ORM, чтобы уже загруженные объекты не остались с несвежим составом
    user = await session.scalar(
        select(User).options(selectinload(User.sites)).where(User.id == user_id)
    )
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    fields = data.model_dump(exclude_unset=True)

    # защита от самоблокировки: разжаловав или деактивировав себя,
    # админ мог бы оставить систему вовсе без администратора
    if user.id == current.id and {"role", "is_active"} & fields.keys():
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Нельзя менять роль или активность самому себе"
        )

    was_foreman = user.role == UserRole.FOREMAN
    if "password" in fields:
        password = fields.pop("password")
        user.password_hash = await run_in_threadpool(hash_password, password) if password else None
    for name, value in fields.items():
        setattr(user, name, value)

    if user.password_hash is not None and user.email is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Пользователю с паролем нужен email для входа"
        )

    # бывший прораб не должен тихо сохранять привязки: вернись он в прорабы,
    # старые объекты снова стали бы ему видны
    if was_foreman and user.role != UserRole.FOREMAN:
        user.sites.clear()

    try:
        await session.commit()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, _conflict_detail(exc)) from None
    return UserOut.model_validate(user)
