from app.dao.base import BaseDAO
from app.payments.models import PaymentTransaction

class TransactionDAO(BaseDAO):
    model = PaymentTransaction