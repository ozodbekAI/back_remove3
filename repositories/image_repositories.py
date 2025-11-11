from sqlalchemy import select, and_, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from database.models import ProcessedImage, User, Payment
from datetime import datetime, timedelta, timezone
from utils.logger import logger

class ImageRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self, 
        user_id: int, 
        image_key: str,
        original_file_id: str,
        standard_transparent_file_id: str,
        standard_bw_file_id: str,
        watermarked_transparent_file_id: str,
        watermarked_bw_file_id: str
    ) -> ProcessedImage:
        image = ProcessedImage(
            user_id=user_id,
            image_key=image_key,
            original_file_id=original_file_id,
            standard_transparent_file_id=standard_transparent_file_id,
            standard_bw_file_id=standard_bw_file_id,
            watermarked_transparent_file_id=watermarked_transparent_file_id,
            watermarked_bw_file_id=watermarked_bw_file_id
        )
        self.session.add(image)
        await self.session.commit()
        await self.session.refresh(image)
        logger.info(f"✅ Created ProcessedImage with file_ids for {image_key}")
        return image

    async def save_improved_versions(
        self,
        image_key: str,
        improved_transparent_file_id: str,
        improved_bw_file_id: str,
        watermarked_improved_transparent_file_id: str,
        watermarked_improved_bw_file_id: str
    ):
        stmt = update(ProcessedImage).where(
            ProcessedImage.image_key == image_key
        ).values(
            improved_transparent_file_id=improved_transparent_file_id,
            improved_bw_file_id=improved_bw_file_id,
            watermarked_improved_transparent_file_id=watermarked_improved_transparent_file_id,
            watermarked_improved_bw_file_id=watermarked_improved_bw_file_id
        )
        await self.session.execute(stmt)
        await self.session.commit()
        logger.info(f"✅ Saved improved file_ids for {image_key}")

    async def get_by_key(self, image_key: str) -> ProcessedImage:
        stmt = select(ProcessedImage).where(ProcessedImage.image_key == image_key)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def mark_as_paid(self, image_key: str):
        stmt = update(ProcessedImage).where(
            ProcessedImage.image_key == image_key
        ).values(is_paid=True)
        await self.session.execute(stmt)
        await self.session.commit()

    async def count_unpaid_last_24h(self, telegram_id: int) -> int:
        time_24h_ago = datetime.now(timezone.utc) - timedelta(hours=24)
        
        stmt = select(func.count(ProcessedImage.id)).select_from(ProcessedImage).join(
            User, ProcessedImage.user_id == User.id
        ).where(
            and_(
                User.telegram_id == telegram_id,
                ProcessedImage.created_at >= time_24h_ago,
                ProcessedImage.is_paid == False
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar()

    async def get_unpaid_images_for_discount(self) -> list[ProcessedImage]:
        stmt = select(ProcessedImage).options(
            selectinload(ProcessedImage.user)
        ).where(
            ProcessedImage.is_paid == False
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def save_message_ids(self, image_key: str, message_ids: list):
        stmt = update(ProcessedImage).where(
            ProcessedImage.image_key == image_key
        ).values(last_message_ids=message_ids)
        await self.session.execute(stmt)
        await self.session.commit()

    async def get_last_message_ids(self, image_key: str) -> list:
        stmt = select(ProcessedImage.last_message_ids).where(
            ProcessedImage.image_key == image_key
        )
        result = await self.session.execute(stmt)
        message_ids = result.scalar_one_or_none()
        return message_ids if message_ids else []

    async def save_improved_message_ids(self, image_key: str, message_ids: list):
        stmt = update(ProcessedImage).where(
            ProcessedImage.image_key == image_key
        ).values(improved_message_ids=message_ids)
        await self.session.execute(stmt)
        await self.session.commit()

    async def get_improved_message_ids(self, image_key: str) -> list:
        stmt = select(ProcessedImage.improved_message_ids).where(
            ProcessedImage.image_key == image_key
        )
        result = await self.session.execute(stmt)
        message_ids = result.scalar_one_or_none()
        return message_ids if message_ids else []

    async def save_discount_message_ids(self, image_key: str, discount: int, message_ids: list):
        field_map = {
            290: "discount_290_message_ids",
            190: "discount_190_message_ids",
            99: "discount_99_message_ids"
        }
        
        field = field_map.get(discount)
        if not field:
            return
        
        stmt = update(ProcessedImage).where(
            ProcessedImage.image_key == image_key
        ).values(**{field: message_ids})
        await self.session.execute(stmt)
        await self.session.commit()

    async def get_discount_message_ids(self, image_key: str, discount: int) -> list:
        field_map = {
            290: "discount_290_message_ids",
            190: "discount_190_message_ids",
            99: "discount_99_message_ids"
        }
        
        field = field_map.get(discount)
        if not field:
            return []
        
        stmt = select(getattr(ProcessedImage, field)).where(
            ProcessedImage.image_key == image_key
        )
        result = await self.session.execute(stmt)
        message_ids = result.scalar_one_or_none()
        return message_ids if message_ids else []

    async def mark_discount_sent(self, image_key: str, discount_amount: int):
        field_map = {
            490: "improved_sent",
            290: "discount_sent_290",
            190: "discount_sent_190",
            99: "discount_sent_99"
        }
        
        field = field_map.get(discount_amount)
        if not field:
            return
        
        stmt = update(ProcessedImage).where(
            ProcessedImage.image_key == image_key
        ).values(**{field: True})
        await self.session.execute(stmt)
        await self.session.commit()