from aiogram import Bot
from aiogram.types import BufferedInputFile
from utils.logger import logger
from config import settings
from typing import Optional, Dict

class TelegramStorage:
    
    @staticmethod
    async def upload_image(bot: Bot, image_bytes: bytes, 
                          filename: str, caption: str = None) -> Optional[str]:
        try:
            channel_id = settings.storage_channel_id
            document = BufferedInputFile(image_bytes, filename=filename)
            
            message = await bot.send_document(
                chat_id=channel_id,
                document=document,
                caption=caption or filename
            )
            
            file_id = message.document.file_id
            logger.info(f"✅ Uploaded {filename} to channel, file_id: {file_id}")
            return file_id
            
        except Exception as e:
            logger.error(f"❌ Failed to upload {filename}: {e}")
            return None
    
    @staticmethod
    async def upload_standard_versions(
        bot: Bot,
        original_bytes: bytes,
        transparent_bytes: bytes,
        bw_bytes: bytes,
        transparent_watermarked: bytes,
        bw_watermarked: bytes,
        image_key: str
    ) -> Dict[str, str]:
        original_id = await TelegramStorage.upload_image(
            bot, original_bytes,
            f"original_{image_key}.png",
            f"🔹 ORIGINAL - {image_key}"
        )
        
        transparent_id = await TelegramStorage.upload_image(
            bot, transparent_bytes,
            f"std_transparent_{image_key}.png",
            f"🔹 STANDARD Transparent (Clean) - {image_key}"
        )
        
        bw_id = await TelegramStorage.upload_image(
            bot, bw_bytes,
            f"std_bw_{image_key}.png",
            f"🔹 STANDARD B&W (Clean) - {image_key}"
        )
        
        watermarked_trans_id = await TelegramStorage.upload_image(
            bot, transparent_watermarked,
            f"std_transparent_wm_{image_key}.png",
            f"🔸 STANDARD Transparent (Watermarked) - {image_key}"
        )
        
        watermarked_bw_id = await TelegramStorage.upload_image(
            bot, bw_watermarked,
            f"std_bw_wm_{image_key}.png",
            f"🔸 STANDARD B&W (Watermarked) - {image_key}"
        )
        
        return {
            'original_file_id': original_id,
            'standard_transparent_file_id': transparent_id,
            'standard_bw_file_id': bw_id,
            'watermarked_transparent_file_id': watermarked_trans_id,
            'watermarked_bw_file_id': watermarked_bw_id
        }
    
    @staticmethod
    async def upload_improved_versions(
        bot: Bot,
        transparent_bytes: bytes,
        bw_bytes: bytes,
        transparent_watermarked: bytes,
        bw_watermarked: bytes,
        image_key: str
    ) -> Dict[str, str]:
        transparent_id = await TelegramStorage.upload_image(
            bot, transparent_bytes,
            f"imp_transparent_{image_key}.png",
            f"✨ IMPROVED Transparent (Clean) - {image_key}"
        )
        
        bw_id = await TelegramStorage.upload_image(
            bot, bw_bytes,
            f"imp_bw_{image_key}.png",
            f"✨ IMPROVED B&W (Clean) - {image_key}"
        )
        
        watermarked_trans_id = await TelegramStorage.upload_image(
            bot, transparent_watermarked,
            f"imp_transparent_wm_{image_key}.png",
            f"✨ IMPROVED Transparent (Watermarked) - {image_key}"
        )
        
        watermarked_bw_id = await TelegramStorage.upload_image(
            bot, bw_watermarked,
            f"imp_bw_wm_{image_key}.png",
            f"✨ IMPROVED B&W (Watermarked) - {image_key}"
        )
        
        return {
            'improved_transparent_file_id': transparent_id,
            'improved_bw_file_id': bw_id,
            'watermarked_improved_transparent_file_id': watermarked_trans_id,
            'watermarked_improved_bw_file_id': watermarked_bw_id
        }
    
    @staticmethod
    async def send_from_storage(bot: Bot, file_id: str, 
                               chat_id: int, caption: str = None):
        try:
            await bot.send_document(
                chat_id=chat_id,
                document=file_id,
                caption=caption
            )
            logger.info(f"✅ Sent file_id {file_id[:20]}... to user {chat_id}")
        except Exception as e:
            logger.error(f"❌ Failed to send file_id: {e}")
            raise