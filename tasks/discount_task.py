from celery import Celery
from config import settings
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from utils.logger import logger
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool
from repositories.image_repositories import ImageRepository
from services.image_service import ImageService
from services.telegram_storage import TelegramStorage
from datetime import datetime, timedelta, timezone

celery_app = Celery(
    'photo_bot',
    broker=settings.redis_url,
    backend=settings.redis_url
)

celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
    beat_schedule={
        'send-improved-versions': {
            'task': 'tasks.discount_tasks.send_improved_versions',
            'schedule': 30,
        },
    },
)


async def delete_previous_messages(bot, telegram_id: int, message_ids: list):
    if not message_ids:
        return
    
    for msg_id in message_ids:
        try:
            await bot.delete_message(telegram_id, msg_id)
            logger.info(f"Deleted message {msg_id} for user {telegram_id}")
        except Exception as e:
            logger.warning(f"Could not delete message {msg_id}: {e}")
        await asyncio.sleep(0.1)


async def process_and_upload_improved_version(bot, original_file_id: str, image_key: str) -> dict:

    try:
        logger.info(f"📥 Downloading original from channel for {image_key}")
        file = await bot.get_file(original_file_id)
        original_bytes = await bot.download_file(file.file_path)
        original_bytes = original_bytes.read()
        
        logger.info(f"✨ Creating improved version for {image_key}")
        transparent_improved = ImageService.remove_background(original_bytes, improved=True)
        
        if not transparent_improved or len(transparent_improved) == 0:
            raise ValueError("Improved background removal returned empty data")
        
        bw_improved = ImageService.convert_to_black_and_white(transparent_improved)
        
        if not bw_improved or len(bw_improved) == 0:
            raise ValueError("B&W conversion returned empty data")
        
        logger.info(f"💧 Adding watermarks to improved for {image_key}")
        transparent_watermarked = ImageService.add_watermarks(transparent_improved)
        bw_watermarked = ImageService.add_watermarks(bw_improved)
        
        logger.info(f"📤 Uploading improved versions to channel for {image_key}")
        file_ids = await TelegramStorage.upload_improved_versions(
            bot=bot,
            transparent_bytes=transparent_improved,
            bw_bytes=bw_improved,
            transparent_watermarked=transparent_watermarked,
            bw_watermarked=bw_watermarked,
            image_key=image_key
        )
        
        logger.info(f"✅ Improved versions uploaded successfully for {image_key}")
        return file_ids
        
    except Exception as e:
        logger.error(f"Failed to create improved version for {image_key}: {e}")
        raise


async def send_improved_offer(bot, telegram_id: int, image_key: str,
                              watermarked_trans_file_id: str,
                              watermarked_bw_file_id: str,
                              stage: str):
    try:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"💳 Купить за {settings.price}₽",
                callback_data=f"pay_{telegram_id}_{image_key}"
            )],
            [InlineKeyboardButton(text="Не нравится результат", callback_data="not_like")]
        ])
        
        message_text = (
            f"✨ УЛУЧШЕННАЯ ВЕРСИЯ вашей фотографии!\n\n"
            f"🎯 Более качественная обработка:\n"
            f"• Лучше вырезаны детали\n"
            f"• Четче края\n"
            f"• Профессиональное качество\n\n"
            f"💰 Цена: {settings.price}₽\n"
            f"Получите версию БЕЗ водяных знаков!"
        )
        msg1 = await bot.send_document(
            telegram_id,
            document=watermarked_trans_file_id,
            caption="1️⃣ Прозрачный фон (улучшенная, с водяными знаками)"
        )
        
        msg2 = await bot.send_document(
            telegram_id,
            document=watermarked_bw_file_id,
            caption="2️⃣ Черно-белая (улучшенная, с водяными знаками)"
        )
        
        msg3 = await bot.send_message(
            telegram_id,
            message_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

        logger.info(f"✅ Improved offer sent to user {telegram_id} for {image_key}")
        
        return [msg1.message_id, msg2.message_id, msg3.message_id]
        
    except Exception as e:
        logger.error(f"Failed to send improved offer to {telegram_id}: {e}")
        return []


async def send_discount_offer(bot, telegram_id: int, image_key: str, price: int,
                              watermarked_std_trans_id: str,
                              watermarked_std_bw_id: str,
                              watermarked_imp_trans_id: str = None,
                              watermarked_imp_bw_id: str = None):
    try:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"💳 Купить за {price}₽ (скидка!)",
                callback_data=f"discount_pay_{telegram_id}_{image_key}_{price}"
            )],
            [InlineKeyboardButton(text="Не нравится результат", callback_data="not_like")]
        ])
        
        original_price = settings.price
        discount_percent = int(((original_price - price) / original_price) * 100)
        
        message_text = (
            f"🔥 СПЕЦИАЛЬНАЯ ЦЕНА!\n\n"
            f"💰 Скидка {discount_percent}%!\n"
            f"~~{original_price}₽~~ → **{price}₽**\n\n"
            f"📦 Вы получите ВСЕ 4 версии:\n"
            f"• Стандартная + Улучшенная\n"
            f"• Прозрачный фон + Черно-белая\n\n"
            f"⏰ Предложение ограничено!"
        )
        
        messages = []
        
        msg1 = await bot.send_document(
            telegram_id,
            document=watermarked_std_trans_id,
            caption="1️⃣ Стандартная (прозрачный фон)"
        )
        messages.append(msg1.message_id)
        
        msg2 = await bot.send_document(
            telegram_id,
            document=watermarked_std_bw_id,
            caption="2️⃣ Стандартная (черно-белая)"
        )
        messages.append(msg2.message_id)
        
        if watermarked_imp_trans_id and watermarked_imp_bw_id:
            msg3 = await bot.send_document(
                telegram_id,
                document=watermarked_imp_trans_id,
                caption="3️⃣ Улучшенная (прозрачный фон)"
            )
            messages.append(msg3.message_id)
            
            msg4 = await bot.send_document(
                telegram_id,
                document=watermarked_imp_bw_id,
                caption="4️⃣ Улучшенная (черно-белая)"
            )
            messages.append(msg4.message_id)
        
        msg_final = await bot.send_message(
            telegram_id,
            message_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        messages.append(msg_final.message_id)

        logger.info(f"✅ Discount {price}₽ sent to user {telegram_id} for {image_key}")
        return messages
        
    except Exception as e:
        logger.error(f"Failed to send discount to {telegram_id}: {e}")
        return []


async def process_discounts():
    bot = Bot(token=settings.bot_token)
    engine = create_async_engine(
        settings.database_url.replace("postgresql://", "postgresql+asyncpg://"),
        echo=False,
        poolclass=NullPool,
    )
    async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    try:
        async with async_session_maker() as session:
            image_repo = ImageRepository(session)
            unpaid_images = await image_repo.get_unpaid_images_for_discount()
            
            now = datetime.now(timezone.utc)
            logger.info(f"⏰ Checking at {now}, found {len(unpaid_images)} unpaid images")
            
            for image in unpaid_images:
                if image.is_paid:
                    continue
                
                telegram_id = image.user.telegram_id
                created_at = image.created_at
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                
                elapsed = now - created_at
                elapsed_minutes = elapsed.total_seconds() / 60
                
                time_improved = 2
                time_290 = 4
                time_190 = 6
                time_99 = 8

                if (elapsed_minutes >= time_improved and 
                    not image.improved_sent and 
                    not image.is_paid and
                    image.original_file_id):
                    
                    logger.info(f"📤 Creating improved for {image.image_key}")
                    
                    try:
                        file_ids = await process_and_upload_improved_version(
                            bot, image.original_file_id, image.image_key
                        )
                        
                        await image_repo.save_improved_versions(
                            image.image_key,
                            file_ids['improved_transparent_file_id'],
                            file_ids['improved_bw_file_id'],
                            file_ids['watermarked_improved_transparent_file_id'],
                            file_ids['watermarked_improved_bw_file_id']
                        )
                        
                        message_ids = await send_improved_offer(
                            bot, telegram_id, image.image_key,
                            file_ids['watermarked_improved_transparent_file_id'],
                            file_ids['watermarked_improved_bw_file_id'],
                            "improved"
                        )
                        
                        if message_ids:
                            await image_repo.save_improved_message_ids(image.image_key, message_ids)
                        
                        await image_repo.mark_discount_sent(image.image_key, 490)
                        await asyncio.sleep(0.5)
                        continue
                        
                    except Exception as e:
                        logger.error(f"Failed improved for {image.image_key}: {e}")
                        continue

                if (elapsed_minutes >= time_290 and 
                    image.improved_sent and
                    not image.discount_sent_290 and 
                    not image.is_paid):
                    
                    logger.info(f"📤 Sending 290₽ discount for {image.image_key}")
                    
                    message_ids = await send_discount_offer(
                        bot, telegram_id, image.image_key, 290,
                        image.watermarked_transparent_file_id,
                        image.watermarked_bw_file_id,
                        image.watermarked_improved_transparent_file_id,
                        image.watermarked_improved_bw_file_id
                    )
                    
                    old_ids = await image_repo.get_last_message_ids(image.image_key)
                    if old_ids:
                        await delete_previous_messages(bot, telegram_id, old_ids)
                    
                    old_imp_ids = await image_repo.get_improved_message_ids(image.image_key)
                    if old_imp_ids:
                        await delete_previous_messages(bot, telegram_id, old_imp_ids)
                    
                    if message_ids:
                        await image_repo.save_discount_message_ids(image.image_key, 290, message_ids)
                    
                    await image_repo.mark_discount_sent(image.image_key, 290)
                    await asyncio.sleep(0.5)
                    continue

                if (elapsed_minutes >= time_190 and 
                    image.discount_sent_290 and
                    not image.discount_sent_190 and 
                    not image.is_paid):
                    
                    logger.info(f"📤 Sending 190₽ discount for {image.image_key}")
                    
                    message_ids = await send_discount_offer(
                        bot, telegram_id, image.image_key, 190,
                        image.watermarked_transparent_file_id,
                        image.watermarked_bw_file_id,
                        image.watermarked_improved_transparent_file_id,
                        image.watermarked_improved_bw_file_id
                    )
                    
                    old_ids = await image_repo.get_discount_message_ids(image.image_key, 290)
                    if old_ids:
                        await delete_previous_messages(bot, telegram_id, old_ids)
                    
                    if message_ids:
                        await image_repo.save_discount_message_ids(image.image_key, 190, message_ids)
                    
                    await image_repo.mark_discount_sent(image.image_key, 190)
                    await asyncio.sleep(0.5)
                    continue

                if (elapsed_minutes >= time_99 and 
                    image.discount_sent_190 and
                    not image.discount_sent_99 and 
                    not image.is_paid):
                    
                    logger.info(f"📤 Sending 99₽ final discount for {image.image_key}")
                    
                    message_ids = await send_discount_offer(
                        bot, telegram_id, image.image_key, 99,
                        image.watermarked_transparent_file_id,
                        image.watermarked_bw_file_id,
                        image.watermarked_improved_transparent_file_id,
                        image.watermarked_improved_bw_file_id
                    )
                    
                    old_ids = await image_repo.get_discount_message_ids(image.image_key, 190)
                    if old_ids:
                        await delete_previous_messages(bot, telegram_id, old_ids)
                    
                    if message_ids:
                        await image_repo.save_discount_message_ids(image.image_key, 99, message_ids)
                    
                    await image_repo.mark_discount_sent(image.image_key, 99)
                    await asyncio.sleep(0.5)
                    continue
            
            logger.info("✅ Discount check completed")
        
    except Exception as e:
        logger.error(f"❌ Error in process_discounts: {e}", exc_info=True)
    finally:
        await bot.session.close()
        await engine.dispose()


@celery_app.task(name='tasks.discount_tasks.send_improved_versions', bind=True)
def send_improved_versions(self):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(process_discounts())
    finally:
        loop.close()
    logger.info("✅ Discount task finished")