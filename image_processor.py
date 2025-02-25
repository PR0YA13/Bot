from PIL import Image, ImageEnhance
import io
import logging
from typing import Dict, Tuple, Optional

logger = logging.getLogger(__name__)

class ImageProcessor:
    PREVIEW_SIZE = (200, 200)  # Размер превью

    @staticmethod
    def _apply_enhancements(image: Image.Image, brightness: float = 1.0, contrast: float = 1.0, sharpness: float = 1.0) -> Image.Image:
        """
        Apply multiple enhancements to an image
        """
        if brightness != 1.0:
            image = ImageEnhance.Brightness(image).enhance(brightness)
        if contrast != 1.0:
            image = ImageEnhance.Contrast(image).enhance(contrast)
        if sharpness != 1.0:
            image = ImageEnhance.Sharpness(image).enhance(sharpness)
        return image

    @staticmethod
    def create_preset_preview(image_data: bytes) -> Dict[str, bytes]:
        """
        Creates preview images for all presets
        """
        try:
            preview_dict = {}
            image = Image.open(io.BytesIO(image_data))

            # Создаем миниатюру
            image.thumbnail(ImageProcessor.PREVIEW_SIZE)

            presets = {
                'none': {'brightness': 1.0, 'contrast': 1.0, 'sharpness': 1.0},
                'default': {'brightness': 1.1, 'contrast': 1.1, 'sharpness': 1.0},
                'high_contrast': {'brightness': 1.0, 'contrast': 1.5, 'sharpness': 1.2},
                'bright': {'brightness': 1.3, 'contrast': 1.1, 'sharpness': 1.0},
                'sharp': {'brightness': 1.0, 'contrast': 1.2, 'sharpness': 1.5},
                'balanced': {'brightness': 1.15, 'contrast': 1.15, 'sharpness': 1.1}
            }

            for preset_name, params in presets.items():
                preview = ImageProcessor._apply_enhancements(image.copy(), **params)
                output = io.BytesIO()
                preview.save(output, format='PNG', optimize=True)
                preview_dict[preset_name] = output.getvalue()

            return preview_dict

        except Exception as e:
            logger.error(f"Preview creation error: {str(e)}")
            return {}

    @staticmethod
    def process_image(image_data: bytes, preset: str = 'default') -> bytes:
        """
        Process image with predefined presets
        """
        try:
            image = Image.open(io.BytesIO(image_data))

            presets = {
                'none': {'brightness': 1.0, 'contrast': 1.0, 'sharpness': 1.0},
                'default': {'brightness': 1.1, 'contrast': 1.1, 'sharpness': 1.0},
                'high_contrast': {'brightness': 1.0, 'contrast': 1.5, 'sharpness': 1.2},
                'bright': {'brightness': 1.3, 'contrast': 1.1, 'sharpness': 1.0},
                'sharp': {'brightness': 1.0, 'contrast': 1.2, 'sharpness': 1.5},
                'balanced': {'brightness': 1.15, 'contrast': 1.15, 'sharpness': 1.1}
            }

            if preset not in presets:
                logger.warning(f"Unknown preset {preset}, using default")
                preset = 'default'

            # Для пресета 'none' просто возвращаем оригинальное изображение
            if preset == 'none':
                output = io.BytesIO()
                image.save(output, format='PNG', optimize=True)
                return output.getvalue()

            params = presets[preset]
            enhanced = ImageProcessor._apply_enhancements(image, **params)

            output = io.BytesIO()
            enhanced.save(output, format='PNG', optimize=True)
            return output.getvalue()

        except Exception as e:
            logger.error(f"Image processing error: {str(e)}")
            return image_data

    @staticmethod
    def convert_format(image_data: bytes, target_format: str) -> bytes:
        """
        Convert image to specified format
        """
        try:
            image = Image.open(io.BytesIO(image_data))
            output = io.BytesIO()
            image.save(output, format=target_format, optimize=True)
            return output.getvalue()
        except Exception as e:
            logger.error(f"Format conversion error: {str(e)}")
            return image_data