# from fastapi import APIRouter, Depends
#
# from app.database import SessionDep
# from app.payments.models import TxTypeEnum
# from app.users.auth import get_current_user
# from app.users.models import User
#
# router = APIRouter(prefix="/payments", tags=["Payments"])
#
# @router.post("/paycash")
# async def paycash(req: DepositRequest, session: SessionDep, current_user: User = Depends(get_current_user)):
#     # 1. создаём транзакцию
#     tx = await PaymentTransactionDAO.add(
#         session,
#         user_id=current_user.id,
#         type=TxTypeEnum.DEPOSIT,
#         amount=req.amount,
#         status=TxStatusEnum.PENDING,
#     )
#
#     # 2. зовём PLAT API
#     plat = PlatClient(api_key=settings.PLAT_KEY)
#     ext_id, pay_url = await plat.create_payment(amount=req.amount, tx_id=tx.id)
#
#     # 3. обновляем транзакцию
#     await PaymentTransactionDAO.update(session, {"id": tx.id}, ext_ref=ext_id)
#
#     return {"tx_id": tx.id, "pay_url": pay_url}
#
# @router.post("/pullcash")
# async def pullcash(req: WithdrawRequest, session: SessionDep, current_user: User = Depends(get_current_user)):
#     if current_user.balance < req.amount:
#         raise HTTPException(status_code=400, detail="Недостаточно средств")
#
#     # 1. создаём транзакцию
#     tx = await PaymentTransactionDAO.add(
#         session,
#         user_id=current_user.id,
#         type=TxTypeEnum.WITHDRAW,
#         amount=req.amount,
#         status=TxStatusEnum.PENDING,
#     )
#
#     # 2. зовём PLAT API
#     plat = PlatClient(api_key=settings.PLAT_KEY)
#     ext_id = await plat.create_payout(amount=req.amount, tx_id=tx.id, user=current_user)
#
#     # 3. сохраняем внешний id
#     await PaymentTransactionDAO.update(session, {"id": tx.id}, ext_ref=ext_id)
#
#     return {"tx_id": tx.id, "status": "pending"}