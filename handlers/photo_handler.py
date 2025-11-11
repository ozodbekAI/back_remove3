import asyncio
import uuid
from aiogram import Router, F
from aiogram.types import Message, BufferedInputFile
from aiogram.fsm.context import FSMContext
from services.image_service import ImageService
from services.telegram_storage import TelegramStorage
from keyboards.inline_keyboards import get_result_keyboard
from utils.file_utils import download_temp_file, cleanup_file, cleanup_temp_dir
from photos.processor import validate_image_bytes, is_valid_image_file
from config import settings
from utils.logger import logger
from database.connection import get_async_session
from repositories.image_repositories import ImageRepository
from repositories.user_repository import UserRepository

router = Router()

user_queues = {}
user_locks = {}

async def process_image_with_retry(original_bytes, retries=2, improved=False):
    last_exception = None
    for attempt in range(1, retries + 1):
        try:
            transparent_bytes = ImageService.remove_background(original_bytes, improved=improved)
            bw_bytes = ImageService.convert_to_black_and_white(transparent_bytes)
            return transparent_bytes, bw_bytes
        except Exception as e:
            last_exception = e
            await asyncio.sleep(1)
    raise last_exception


async def check_spam_limit(user_id: int) -> tuple[bool, bool]:
    async for session in get_async_session():
        image_repo = ImageRepository(session)
        user_repo = UserRepository(session)
        
        has_payment = await user_repo.has_paid(user_id)
        if has_payment:
            return False, True
        
        unpaid_count = await image_repo.count_unpaid_last_24h(user_id)
        if unpaid_count >= 20:
            return True, False
        
        return False, False


async def process_and_send_images(
    message: Message,
    state: FSMContext,
    original_bytes: bytes,
    user_id: int
):
    
    is_limited, has_payment = await check_spam_limit(user_id)
    
    if is_limited:
        await message.answer(
            "⚠️ Вы достигли лимита обработок.\n"
            "Пожалуйста, попробуйте завтра или оплатите любую фотографию для безлимитной обработки."
        )
        return
    
    image_key = str(uuid.uuid4())
    logger.info(f"🔑 User {user_id}: Generated key {image_key}")
    
    logger.info(f"🎨 Processing standard versions for {image_key}")
    transparent_bytes, bw_bytes = await process_image_with_retry(
        original_bytes, retries=2, improved=False
    )
    
    logger.info(f"💧 Adding watermarks for {image_key}")
    transparent_watermarked = ImageService.add_watermarks(transparent_bytes)
    bw_watermarked = ImageService.add_watermarks(bw_bytes)
    
    logger.info(f"📤 Uploading to channel for {image_key}")
    file_ids = await TelegramStorage.upload_standard_versions(
        bot=message.bot,
        original_bytes=original_bytes,
        transparent_bytes=transparent_bytes,
        bw_bytes=bw_bytes,
        transparent_watermarked=transparent_watermarked,
        bw_watermarked=bw_watermarked,
        image_key=image_key
    )
    
    async for session in get_async_session():
        image_repo = ImageRepository(session)
        user_repo = UserRepository(session)
        
        user = await user_repo.get_or_create(user_id)
        await image_repo.create(
            user.id,
            image_key,
            original_file_id=file_ids['original_file_id'],
            standard_transparent_file_id=file_ids['standard_transparent_file_id'],
            standard_bw_file_id=file_ids['standard_bw_file_id'],
            watermarked_transparent_file_id=file_ids['watermarked_transparent_file_id'],
            watermarked_bw_file_id=file_ids['watermarked_bw_file_id']
        )
    
    logger.info(f"📨 Sending watermarked previews to user {user_id}")
    
    markup = get_result_keyboard(user_id, image_key, settings.price)
    
    doc1 = BufferedInputFile(transparent_watermarked, filename=f"transparent_watermarked.png")
    msg1 = await message.answer_document(
        document=doc1,
        caption="1️⃣ Прозрачный фон (с водяными знаками)",
        reply_to_message_id=message.message_id
    )
    
    doc2 = BufferedInputFile(bw_watermarked, filename=f"bw_watermarked.png")
    msg2 = await message.answer_document(
        document=doc2,
        caption="2️⃣ Черно-белая (с водяными знаками)"
    )
    
    caption = (
        f"✅ Готово — 2 версии с водяными знаками!\n\n"
        f"💰 Полные версии без водяных знаков — {settings.price}₽\n"
        f"Нажмите кнопку ниже, чтобы оплатить."
    )
    
    result_msg = await message.answer(
        caption,
        reply_markup=markup,
        parse_mode="Markdown"
    )
    
    message_ids = [msg1.message_id, msg2.message_id, result_msg.message_id]
    
    async for session in get_async_session():
        image_repo = ImageRepository(session)
        await image_repo.save_message_ids(image_key, message_ids)
    
    data = await state.get_data()
    images = data.get('images', {})
    images[image_key] = {
        'paid': False,
        'result_msg_id': result_msg.message_id,
        'price': settings.price,
        'version': 'standard'
    }
    await state.update_data(images=images)
    
    logger.info(f"✅ Completed processing for {image_key}")


async def process_queue(user_id: int):
    if user_id not in user_queues:
        return
    
    while user_queues[user_id]:
        task = user_queues[user_id][0]
        
        try:
            await task['func'](
                task['message'],
                task['state'],
                task['original_bytes'],
                task['user_id']
            )
        except Exception as e:
            logger.exception(f"Error processing queued image for user {user_id}: {e}")
            try:
                await task['message'].answer("❌ Ошибка при обработке фото.")
            except:
                pass
        finally:
            user_queues[user_id].pop(0)
            
            if task.get('temp_path'):
                cleanup_file(task['temp_path'])
            if task.get('temp_dir'):
                cleanup_temp_dir(task['temp_dir'])
    
    if user_id in user_locks:
        del user_locks[user_id]


async def add_to_queue(message: Message, state: FSMContext, original_bytes: bytes, 
                       user_id: int, temp_path: str = None, temp_dir: str = None):
    if user_id not in user_queues:
        user_queues[user_id] = []
    
    task = {
        'func': process_and_send_images,
        'message': message,
        'state': state,
        'original_bytes': original_bytes,
        'user_id': user_id,
        'temp_path': temp_path,
        'temp_dir': temp_dir
    }
    
    user_queues[user_id].append(task)
    logger.info(f"📝 Added to queue for user {user_id}. Queue size: {len(user_queues[user_id])}")
    
    if user_id not in user_locks:
        user_locks[user_id] = True
        asyncio.create_task(process_queue(user_id))


@router.message(F.photo)
async def photo_handler(message: Message, state: FSMContext):
    user_id = message.from_user.id

    if message.caption:
        return

    temp_path = temp_dir = None
    try:
        await message.answer("⏳ Обрабатываю изображение... Это может занять до 1 минуты.")

        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)
        temp_path, temp_dir = await download_temp_file(message.bot, file.file_path, user_id)

        with open(temp_path, "rb") as f:
            original_bytes = f.read()

        if not validate_image_bytes(original_bytes):
            await message.answer("❌ Неверный формат фото.")
            cleanup_file(temp_path)
            if temp_dir:
                cleanup_temp_dir(temp_dir)
            return


        await add_to_queue(message, state, original_bytes, user_id, temp_path, temp_dir)

    except Exception as e:
        logger.exception(f"Error in photo_handler: {e}")
        await message.answer("❌ Ошибка при обработке фото.")
        cleanup_file(temp_path)
        if temp_dir:
            cleanup_temp_dir(temp_dir)


@router.message(F.document)
async def document_handler(message: Message, state: FSMContext):
    user_id = message.from_user.id

    if message.caption:
        return

    temp_path = temp_dir = None
    try:
        await message.answer("⏳ Обрабатываю файл...")

        document = message.document
        if not is_valid_image_file(document.file_name, document.mime_type):
            await message.answer("❌ Файл не является изображением.")
            return

        file = await message.bot.get_file(document.file_id)
        temp_path, temp_dir = await download_temp_file(message.bot, file.file_path, user_id)

        with open(temp_path, "rb") as f:
            original_bytes = f.read()

        if not validate_image_bytes(original_bytes):
            await message.answer("❌ Неверный формат файла.")
            cleanup_file(temp_path)
            if temp_dir:
                cleanup_temp_dir(temp_dir)
            return


        await add_to_queue(message, state, original_bytes, user_id, temp_path, temp_dir)

    except Exception as e:
        logger.exception(f"Error in document_handler: {e}")
        await message.answer("❌ Ошибка при обработке файла.")
        cleanup_file(temp_path)
        if temp_dir:
            cleanup_temp_dir(temp_dir)