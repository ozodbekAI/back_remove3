from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from services.payment_service import PaymentService
from services.telegram_storage import TelegramStorage
from keyboards.inline_keyboards import get_payment_keyboard, get_paid_keyboard
from database.connection import get_async_session
from repositories.image_repositories import ImageRepository
from config import settings
from utils.logger import logger
import asyncio
from datetime import datetime, timedelta, timezone

router = Router()


async def send_all_versions_from_storage(
    bot, telegram_id: int, image_key: str, db_image
):

    try:
        if db_image.standard_transparent_file_id:
            await TelegramStorage.send_from_storage(
                bot, db_image.standard_transparent_file_id, telegram_id,
                "✅ 1️⃣ Стандартная версия - прозрачный фон"
            )
        
        if db_image.standard_bw_file_id:
            await TelegramStorage.send_from_storage(
                bot, db_image.standard_bw_file_id, telegram_id,
                "✅ 2️⃣ Стандартная версия - черно-белая"
            )
        
        if db_image.improved_transparent_file_id and db_image.improved_bw_file_id:
            await TelegramStorage.send_from_storage(
                bot, db_image.improved_transparent_file_id, telegram_id,
                "✨ 3️⃣ Улучшенная версия - прозрачный фон"
            )
            
            await TelegramStorage.send_from_storage(
                bot, db_image.improved_bw_file_id, telegram_id,
                "✨ 4️⃣ Улучшенная версия - черно-белая"
            )
            
            await bot.send_message(
                telegram_id,
                "🎉 Спасибо за оплату! Вы получили все 4 версии вашей фотографии!"
            )
        else:
            await bot.send_message(
                telegram_id,
                "✅ Спасибо за оплату! Вы получили 2 версии вашей фотографии!"
            )
        
        logger.info(f"✅ Successfully sent all versions for {image_key}")
            
    except Exception as e:
        logger.error(f"Failed to send versions: {e}")
        await bot.send_message(
            telegram_id,
            "❌ Произошла ошибка при отправке фотографий. Пожалуйста, свяжитесь с поддержкой."
        )


async def handle_payment(
    callback: CallbackQuery,
    state: FSMContext,
    user_id: int,
    image_key: str,
    custom_price: int
):
    try:
        logger.info(f"Payment: user {user_id}, key {image_key}, price {custom_price}")

        processing_markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏳ Оплата в процессе...", callback_data=f"pay_processing_{user_id}_{image_key}")],
            [InlineKeyboardButton(text="Не нравится результат", callback_data="not_like")]
        ])
        await callback.message.edit_reply_markup(reply_markup=processing_markup)

        async for session in get_async_session():
            image_repo = ImageRepository(session)
            db_image = await image_repo.get_by_key(image_key)
            
            if not db_image:
                await callback.answer("❌ Изображение не найдено!", show_alert=True)
                return
            
            invoice_url, invoice_id = await PaymentService.create_invoice(
                session, user_id, custom_price, db_image.id
            )

        invoice_created_at = datetime.now(timezone.utc)
        
        data = await state.get_data()
        images = data.get("images", {})
        if image_key in images:
            images[image_key]['invoice_id'] = invoice_id
            images[image_key]['invoice_created_at'] = invoice_created_at
            images[image_key]['current_price'] = custom_price
            await state.update_data(images=images)

        markup = get_payment_keyboard(invoice_url)
        msg = await callback.message.answer("💳 Перейдите по ссылке для оплаты:", reply_markup=markup)
        await callback.answer()

        asyncio.create_task(
            poll_for_payment(
                telegram_id=user_id,
                invoice_id=invoice_id,
                state=state,
                bot=callback.bot,
                payment_message_id=msg.message_id,
                image_key=image_key,
                result_message_id=callback.message.message_id,
                invoice_created_at=invoice_created_at,
                payment_amount=custom_price
            )
        )

    except Exception as e:
        logger.error(f"Payment error: {e}")
        await callback.answer("Ошибка создания платежа.", show_alert=True)


@router.callback_query(F.data.startswith("discount_pay_"))
async def discount_payment_handler(callback: CallbackQuery, state: FSMContext):
    try:
        parts = callback.data.split("_")
        if len(parts) < 4:
            await callback.answer("❌ Неверный формат!", show_alert=True)
            return
        
        user_id = int(parts[2])
        image_key = parts[3]
        custom_price = int(parts[4]) if len(parts) > 4 else settings.price

        await handle_payment(callback, state, user_id, image_key, custom_price)

    except Exception as e:
        logger.error(f"Discount payment error: {e}")
        await callback.answer("Ошибка создания платежа.", show_alert=True)


@router.callback_query(F.data.startswith("pay_"))
async def regular_payment_handler(callback: CallbackQuery, state: FSMContext):
    try:
        parts = callback.data.split("_")
        if len(parts) < 3:
            await callback.answer("❌ Неверный формат!", show_alert=True)
            return
        
        user_id = int(parts[1])
        image_key = parts[2]
        
        await handle_payment(callback, state, user_id, image_key, settings.price)
        
    except Exception as e:
        logger.error(f"Regular payment error: {e}")
        await callback.answer("Ошибка создания платежа.", show_alert=True)


async def poll_for_payment(
    telegram_id: int,
    invoice_id: str,
    state: FSMContext,
    bot,
    payment_message_id: int,
    image_key: str,
    result_message_id: int,
    invoice_created_at: datetime,
    payment_amount: int
):
    max_wait_time = timedelta(minutes=10)
    check_interval = 10
    max_checks = int(max_wait_time.total_seconds() / check_interval)
    
    for check_count in range(max_checks):
        await asyncio.sleep(check_interval)
        
        elapsed_time = datetime.now(timezone.utc) - invoice_created_at
        if elapsed_time >= max_wait_time:
            logger.info(f"Invoice {invoice_id} expired")
            break
        
        async for session in get_async_session():
            payment_status = await PaymentService.check_status(session, invoice_id)
            
            if payment_status:
                try:
                    await bot.edit_message_text(
                        chat_id=telegram_id,
                        message_id=payment_message_id,
                        text="✅ Оплата получена! Отправляю фотографии..."
                    )
                except:
                    pass

                async for session in get_async_session():
                    image_repo = ImageRepository(session)
                    db_image = await image_repo.get_by_key(image_key)
                    
                    if not db_image:
                        logger.error(f"Image not found for {image_key}")
                        await bot.send_message(telegram_id, "❌ Ошибка: изображение не найдено")
                        return
                    
                    await send_all_versions_from_storage(bot, telegram_id, image_key, db_image)
                    
                    await image_repo.mark_as_paid(image_key)
                    logger.info(f"Marked image {image_key} as paid")

                data = await state.get_data()
                images = data.get("images", {})
                if image_key in images:
                    images[image_key]['paid'] = True
                    await state.update_data(images=images)

                if result_message_id:
                    try:
                        await bot.edit_message_reply_markup(
                            chat_id=telegram_id,
                            message_id=result_message_id,
                            reply_markup=get_paid_keyboard()
                        )
                    except:
                        pass

                try:
                    await bot.delete_message(telegram_id, payment_message_id)
                except:
                    pass

                await asyncio.sleep(2)
                await bot.send_message(
                    telegram_id,
                    f"📸 Хотите обработать ещё одну фотографию?\n"
                    f"Просто отправьте её в чат 👇\n\n"
                    f"💰 Стоимость обработки: {settings.price}₽"
                )
                return
    
    logger.info(f"Invoice {invoice_id} expired without payment")
    
    try:
        await bot.delete_message(telegram_id, payment_message_id)
    except:
        pass
    
    try:
        data = await state.get_data()
        images = data.get("images", {})
        current_price = images.get(image_key, {}).get('current_price', settings.price)
        
        expired_markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Создать новый счет", callback_data=f"discount_pay_{telegram_id}_{image_key}_{current_price}")],
            [InlineKeyboardButton(text="Не нравится результат", callback_data="not_like")]
        ])
        
        if result_message_id:
            await bot.edit_message_reply_markup(
                chat_id=telegram_id,
                message_id=result_message_id,
                reply_markup=expired_markup
            )
        
        await bot.send_message(
            telegram_id,
            "⏰ Время оплаты истекло. Счет больше не действителен.\n"
            "Нажмите '🔄 Создать новый счет' для повторной оплаты."
        )
    except Exception as e:
        logger.error(f"Failed to update expired invoice: {e}")


@router.callback_query(F.data == "not_like")
async def not_like_handler(callback: CallbackQuery):
    await callback.message.answer(
        f"📩 Отправьте фотографию в поддержку {settings.support_username} и опишите проблему."
    )
    await callback.answer()


@router.callback_query(F.data.startswith("pay_processing_"))
async def pay_processing_handler(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    if len(parts) < 4:
        await callback.answer("⏳ Оплата в процессе. Подождите.", show_alert=True)
        return
    
    user_id = int(parts[2])
    image_key = parts[3]
    
    data = await state.get_data()
    images = data.get("images", {})
    
    if image_key not in images:
        await callback.answer("❌ Изображение не найдено!", show_alert=True)
        return
    
    img_data = images[image_key]
    invoice_created_at = img_data.get('invoice_created_at')
    
    if invoice_created_at:
        elapsed = datetime.now(timezone.utc) - invoice_created_at
        if elapsed >= timedelta(minutes=10):
            await callback.answer(
                "⏰ Время оплаты истекло.\n"
                "Нажмите '🔄 Создать новый счет'.",
                show_alert=True
            )
            
            current_price = img_data.get('current_price', settings.price)
            expired_markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Создать новый счет", callback_data=f"discount_pay_{user_id}_{image_key}_{current_price}")],
                [InlineKeyboardButton(text="Не нравится результат", callback_data="not_like")]
            ])
            await callback.message.edit_reply_markup(reply_markup=expired_markup)
        else:
            remaining = timedelta(minutes=10) - elapsed
            minutes = int(remaining.total_seconds() // 60)
            seconds = int(remaining.total_seconds() % 60)
            await callback.answer(
                f"⏳ Оплата в процессе.\n"
                f"Осталось времени: {minutes}м {seconds}с",
                show_alert=True
            )
    else:
        await callback.answer("⏳ Оплата в процессе. Подождите.", show_alert=True)


@router.callback_query(F.data == "paid_done")
async def paid_done_handler(callback: CallbackQuery):
    await callback.answer("✅ Изображения уже отправлены!", show_alert=True)