import requests
import io
import base64
from PIL import Image, ImageDraw, ImageFont
from config import settings
from utils.logger import logger


class ImageService:
    @staticmethod
    def _ensure_bytes(image_data):
        if isinstance(image_data, bytes):
            return image_data
        elif isinstance(image_data, io.BytesIO):
            return image_data.getvalue()
        else:
            raise TypeError(f"Expected bytes, got {type(image_data)}")

    @staticmethod
    def remove_background(image_bytes: bytes, improved: bool = False) -> bytes:
        if settings.test_mode:
            logger.info("TEST MODE: Using test transparent image")
            try:
                path = settings.test_transparent_image_path_improved if improved else settings.test_transparent_image_path
                with open(path, "rb") as f:
                    return f.read()
            except FileNotFoundError:
                logger.error(f"Test image not found")
                return image_bytes
        
        image_bytes = ImageService._ensure_bytes(image_bytes)
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.openrouter_token}",
            "Content-Type": "application/json"
        }

        try:
            logger.info("Removing background")
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            buffered = io.BytesIO()
            image.save(buffered, format="PNG")
            img_str = base64.b64encode(buffered.getvalue()).decode()

            prompt_text = (
                "Remove background with high precision. Pay special attention to hair details, "
                "edges, and fine details. Make the cutout as clean and professional as possible."
            ) if improved else "Delete background"

            payload = {
                "model": "google/gemini-2.5-flash-preview-image",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt_text},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_str}"}}
                        ]
                    }
                ],
                "max_tokens": 0,
                "modalities": ["image", "text"]
            }

            response = requests.post(url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            data = response.json()
            message = data.get("choices", [{}])[0].get("message", {})
            
            if message.get("images"):
                image_obj = message["images"][0]
                if image_obj.get("type") == "image_url":
                    image_url = image_obj["image_url"]["url"]
                    if image_url.startswith("data:image/png;base64,"):
                        base64_data = image_url.split(",")[1]
                        return base64.b64decode(base64_data)
            
            raise ValueError("No image found in response")

        except Exception as e:
            raise Exception(f"Failed to remove background: {e}")

    @staticmethod
    def convert_to_black_and_white(image_bytes: bytes) -> bytes:
        if settings.test_mode:
            logger.info("TEST MODE: Using test BW image")
            try:
                with open(settings.test_bw_image_path, "rb") as f:
                    return f.read()
            except FileNotFoundError:
                logger.error(f"Test BW image not found")
                return image_bytes
        
        image_bytes = ImageService._ensure_bytes(image_bytes)
        
        try:
            image = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
            bw_image = image.convert("L").convert("RGBA")
            
            buffered = io.BytesIO()
            bw_image.save(buffered, format="PNG")
            return buffered.getvalue()
        except Exception as e:
            logger.error(f"Error converting to B&W: {e}")
            raise Exception(f"Failed to convert to black and white: {e}")

    @staticmethod
    def add_watermarks(image_bytes: bytes) -> bytes:
        if settings.test_mode:
            logger.info("TEST MODE: Skipping watermark")
            return image_bytes
        
        image_bytes = ImageService._ensure_bytes(image_bytes)
        image = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        width, height = image.size

        overlay = Image.new('RGBA', image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        font_size = max(13, min(29, min(width, height) // 45))
        font = None
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "C:\\Windows\\Fonts\\arial.ttf",
        ]
        
        for font_path in font_paths:
            try:
                font = ImageFont.truetype(font_path, font_size)
                break
            except (OSError, IOError):
                continue
        
        if font is None:
            try:
                font = ImageFont.load_default(size=font_size)
            except:
                font = ImageFont.load_default()

        text = "Обработка фото"
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        horizontal_spacing = text_width * 1.2
        vertical_spacing = text_height * 1.5
        
        num_cols = int(width / horizontal_spacing) + 2
        num_rows = int(height / vertical_spacing) + 2
        
        total_grid_width = (num_cols - 1) * horizontal_spacing
        total_grid_height = (num_rows - 1) * vertical_spacing
        start_x = (width - total_grid_width) / 2
        start_y = (height - total_grid_height) / 2
        
        for row in range(num_rows):
            for col in range(num_cols):
                x = int(start_x + col * horizontal_spacing)
                y = int(start_y + row * vertical_spacing)
                draw.text((x, y), text, font=font, fill=(0, 0, 0, 200), stroke_width=0)

        watermarked = Image.alpha_composite(image, overlay)
        buffered = io.BytesIO()
        watermarked.save(buffered, format="PNG")
        
        return buffered.getvalue()