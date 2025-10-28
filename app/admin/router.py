from fastapi import APIRouter, HTTPException, Depends, Response, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import status
from typing import Optional

from app.database import SessionDep
from app.admin.dao import AdminDAO
from app.admin.schemas import (
    AdminCreate, AdminOut, LoginRequest, LoginResponse,
    UserAdminOut, UserAdminUpdate, TransactionAdminOut, PlatformStatistics
)
from app.admin.auth import get_password_hash, authenticate_user, create_access_token
from app.admin.dependencies import get_current_admin_user, get_current_super_admin
from app.exception import IncorrectEmailOrPasswordException
from app.users.dao import UserDAO
from app.users.models import User
from app.admin.dao import AdminDAO
from app.payments.dao import PaymentTransactionDAO
from app.payments.models import PaymentTransaction, TxTypeEnum, TxStatusEnum
from sqlalchemy import select
from app.admin.stats_dao import StatsDAO

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.post("/admins", response_model=AdminOut, status_code=201)
async def create_admin(
    admin_data: AdminCreate,
    session: SessionDep,
    admin: User = Depends(get_current_super_admin),
):
    """
    Создание нового администратора (только для суперадминов)
    """
    try:
        new_admin = await AdminDAO.create_admin(
            session=session,
            login=admin_data.login,
            password=admin_data.password,
            name=admin_data.name,
            username=admin_data.username,
            is_super_admin=admin_data.is_super_admin
        )
        return AdminOut.model_validate(new_admin)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка создания администратора: {str(e)}")


@router.post("/login", response_model=LoginResponse, status_code=200)
async def login(
    credentials: LoginRequest,
    session: SessionDep,
    response: Response
):
    """
    Вход в систему администратора
    """
    # Аутентификация пользователя
    user = await authenticate_user(session, credentials.login, credentials.password)
    
    if not user:
        raise IncorrectEmailOrPasswordException
    
    # Проверяем, что пользователь является администратором
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="У вас нет прав администратора"
        )
    
    # Проверяем, что пользователь активен
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ваш аккаунт деактивирован"
        )
    
    # Создаем JWT токен
    access_token = create_access_token(data={"sub": str(user.id)})
    
    # Устанавливаем куку с токеном
    response.set_cookie(
        key="durak_access_token",
        value=access_token,
        httponly=True,
        secure=True,  # Для продакшена должно быть True
        samesite="lax",
        max_age=28800  # 8 часов (8 * 60 * 60)
    )
    
    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        user=AdminOut.model_validate(user)
    )


@router.post("/logout", status_code=200)
async def logout(response: Response):
    """
    Выход из системы администратора
    """
    # Удаляем куку с токеном
    response.delete_cookie(
        key="durak_access_token",
        httponly=True,
        secure=True,
        samesite="lax"
    )
    
    return {"message": "Успешный выход из системы"}


# ============= Эндпоинты для управления пользователями =============


@router.get("/users", response_model=list[UserAdminOut], status_code=200)
async def get_all_users(
    session: SessionDep,
    admin: User = Depends(get_current_admin_user),
    skip: int = Query(0, ge=0, description="Количество записей для пропуска"),
    limit: int = Query(100, ge=1, le=1000, description="Лимит записей"),
    is_admin: Optional[bool] = Query(None, description="Фильтр по администраторам"),
    is_active: Optional[bool] = Query(None, description="Фильтр по активности"),
    is_super_admin: Optional[bool] = Query(None, description="Фильтр по суперадминам"),
):
    """
    Получить список всех пользователей с пагинацией и фильтрами
    """
    filters = {}
    if is_admin is not None:
        filters["is_admin"] = is_admin
    if is_active is not None:
        filters["is_active"] = is_active
    if is_super_admin is not None:
        filters["is_super_admin"] = is_super_admin

    users = await UserDAO.find_all(session, **filters)
    
    # Пагинация
    users = users[skip:skip + limit]
    
    return [UserAdminOut.model_validate(user) for user in users]


@router.get("/users/{user_id}", response_model=UserAdminOut, status_code=200)
async def get_user_by_id(
    user_id: int,
    session: SessionDep,
    admin: User = Depends(get_current_admin_user),
):
    """
    Получить детальную информацию о пользователе
    """
    user = await UserDAO.find_one_or_none_by_id(session, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    return UserAdminOut.model_validate(user)


@router.post("/users/{user_id}/ban", response_model=UserAdminOut, status_code=200)
async def ban_user(
    user_id: int,
    session: SessionDep,
    admin: User = Depends(get_current_admin_user),
):
    """
    Забанить пользователя (установить is_active = False)
    """
    user = await UserDAO.find_one_or_none_by_id(session, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    # Суперадмины не могут быть забанены
    if user.is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нельзя забанить суперадмина"
        )
    
    # Баним пользователя
    updated = await UserDAO.update(session, {"id": user_id}, is_active=False)
    
    return UserAdminOut.model_validate(updated)


@router.post("/users/{user_id}/unban", response_model=UserAdminOut, status_code=200)
async def unban_user(
    user_id: int,
    session: SessionDep,
    admin: User = Depends(get_current_admin_user),
):
    """
    Разбанить пользователя (установить is_active = True)
    """
    user = await UserDAO.find_one_or_none_by_id(session, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    # Разбаниваем пользователя
    updated = await UserDAO.update(session, {"id": user_id}, is_active=True)
    
    return UserAdminOut.model_validate(updated)


@router.patch("/users/{user_id}", response_model=UserAdminOut, status_code=200)
async def update_user(
    user_id: int,
    user_update: UserAdminUpdate,
    session: SessionDep,
    admin: User = Depends(get_current_admin_user),
):
    """
    Изменить данные пользователя
    """
    user = await UserDAO.find_one_or_none_by_id(session, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    # Проверяем, что пытаемся изменить не суперадмина (если текущий админ не суперадмин)
    if user.is_super_admin and not admin.is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Только суперадмин может изменять других суперадминов"
        )
    
    # Обновляем данные пользователя
    update_data = user_update.model_dump(exclude_unset=True, exclude={"password"})
    
    # Если передается password, нужно его захешировать
    if user_update.model_dump(exclude_unset=True).get("password"):
        from app.admin.auth import get_password_hash
        update_data["password"] = get_password_hash(user_update.model_dump(exclude_unset=True)["password"])
    
    updated = await UserDAO.update(session, {"id": user_id}, **update_data)
    
    if not updated:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    return UserAdminOut.model_validate(updated)


# ============= Эндпоинты для управления администраторами =============


@router.get("/admins", response_model=list[AdminOut], status_code=200)
async def get_all_admins_list(
    session: SessionDep,
    admin: User = Depends(get_current_super_admin),
):
    """
    Получить список всех администраторов (только для суперадминов)
    """
    admins = await AdminDAO.get_all_admins(session)
    return [AdminOut.model_validate(adm) for adm in admins]


@router.delete("/admins/{admin_id}", status_code=200)
async def delete_admin(
    admin_id: int,
    session: SessionDep,
    admin: User = Depends(get_current_super_admin),
):
    """
    Удалить администратора (только для суперадминов)
    """
    # Находим администратора
    admin_to_delete = await AdminDAO.find_admin_by_id(session, admin_id)
    if not admin_to_delete:
        raise HTTPException(status_code=404, detail="Администратор не найден")
    
    # Нельзя удалить самого себя
    if admin_to_delete.id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нельзя удалить самого себя"
        )
    
    # Удаляем права администратора (становится обычным пользователем)
    updated = await UserDAO.update(session, {"id": admin_id}, is_admin=False, is_super_admin=False)
    
    if not updated:
        raise HTTPException(status_code=404, detail="Администратор не найден")
    
    return {"message": "Администратор успешно удален"}


@router.patch("/admins/{admin_id}/permissions", response_model=AdminOut, status_code=200)
async def change_admin_permissions(
    admin_id: int,
    is_super_admin: bool = Body(...),
    session: SessionDep = None,
    admin: User = Depends(get_current_super_admin),
):
    """
    Изменить права администратора (сделать суперадмином или убрать статус)
    """
    # Находим администратора
    admin_to_update = await AdminDAO.find_admin_by_id(session, admin_id)
    if not admin_to_update:
        raise HTTPException(status_code=404, detail="Администратор не найден")
    
    # Проверяем, что пользователь является администратором
    if not admin_to_update.is_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пользователь не является администратором"
        )
    
    # Обновляем статус
    updated = await UserDAO.update(
        session, 
        {"id": admin_id}, 
        is_super_admin=is_super_admin
    )
    
    if not updated:
        raise HTTPException(status_code=404, detail="Администратор не найден")
    
    return AdminOut.model_validate(updated)


# ============= Эндпоинты для транзакций =============


@router.get("/transactions", response_model=list[TransactionAdminOut], status_code=200)
async def get_all_transactions(
    session: SessionDep,
    admin: User = Depends(get_current_admin_user),
    skip: int = Query(0, ge=0, description="Количество записей для пропуска"),
    limit: int = Query(100, ge=1, le=1000, description="Лимит записей"),
    type: Optional[str] = Query(None, description="Фильтр по типу транзакции"),
    status: Optional[str] = Query(None, description="Фильтр по статусу транзакции"),
):
    """
    Получить список всех транзакций с пагинацией и фильтрами
    """
    query = select(PaymentTransaction)
    
    # Применяем фильтры
    if type:
        query = query.where(PaymentTransaction.type == type)
    if status:
        query = query.where(PaymentTransaction.status == status)
    
    # Сортировка по дате (новые сначала)
    query = query.order_by(PaymentTransaction.created_at.desc())
    
    result = await session.execute(query)
    transactions = list(result.scalars().all())
    
    # Пагинация
    transactions = transactions[skip:skip + limit]
    
    return [TransactionAdminOut.model_validate(tx) for tx in transactions]


@router.get("/transactions/{transaction_id}", response_model=TransactionAdminOut, status_code=200)
async def get_transaction_by_id(
    transaction_id: int,
    session: SessionDep,
    admin: User = Depends(get_current_admin_user),
):
    """
    Получить детальную информацию о транзакции
    """
    tx = await PaymentTransactionDAO.get_transaction_by_id(session, transaction_id)
    
    if not tx:
        raise HTTPException(status_code=404, detail="Транзакция не найдена")
    
    return TransactionAdminOut.model_validate(tx)


@router.get("/statistics", response_model=PlatformStatistics, status_code=200)
async def get_platform_statistics(
    session: SessionDep,
    admin: User = Depends(get_current_admin_user),
):
    """
    Получить общую статистику платформы
    """
    stats = await StatsDAO.get_platform_statistics(session)
    return PlatformStatistics(**stats)

