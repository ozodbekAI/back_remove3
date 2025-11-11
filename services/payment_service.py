from yookassa import Configuration, Payment
import uuid
from config import settings
from utils.logger import logger
from repositories.user_repository import UserRepository
from repositories.payment_repository import PaymentRepository
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio

Configuration.account_id = settings.yookassa_shop_id
Configuration.secret_key = settings.yookassa_secret_key


class PaymentService:
    @staticmethod
    async def create_invoice(
        session: AsyncSession, 
        telegram_id: int, 
        amount: int = None,
        processed_image_id: int = None
    ) -> tuple[str, str]:
        if amount is None:
            amount = settings.price
            
        user_repo = UserRepository(session)
        user = await user_repo.get_or_create(telegram_id)
        idempotence_key = str(uuid.uuid4())

        for attempt in range(3):
            try:
                payment = Payment.create({
                    "amount": {
                        "value": f"{amount}.00",
                        "currency": "RUB"
                    },
                    "confirmation": {
                        "type": "redirect",
                        "return_url": f"{settings.success_redirect_url}?user={telegram_id}&amount={amount}"
                    },
                    "capture": True,
                    "description": f"Photo processing for user {user.id}",
                    "metadata": {
                        "telegram_id": str(telegram_id),
                        "user_id": str(user.id),
                        "amount": str(amount)
                    }
                }, idempotence_key)

                payment_repo = PaymentRepository(session)
                await payment_repo.create(user.id, payment.id, amount, processed_image_id)

                return payment.confirmation.confirmation_url, payment.id

            except Exception as e:
                logger.error(f"YooKassa create_invoice error: {e}")
                if attempt == 2:
                    raise
                await asyncio.sleep(1)

    @staticmethod
    async def check_status(session: AsyncSession, invoice_id: str) -> bool:
        for attempt in range(3):
            try:
                payment = Payment.find_one(invoice_id)
                if payment.status == "succeeded":
                    payment_repo = PaymentRepository(session)
                    await payment_repo.update_status(invoice_id, "succeeded")
                    return True
                return False
            except Exception as e:
                logger.error(f"YooKassa check_status error: {e}")
                if attempt == 2:
                    return False
                await asyncio.sleep(1)