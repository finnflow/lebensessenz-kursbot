"""
Image upload and validation handler.
Manages temporary storage and preprocessing for vision analysis.
"""
import os
import base64
import uuid
from typing import Optional, Tuple
from pathlib import Path
import imghdr

# Configuration
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "storage/uploads")
MAX_FILE_SIZE = int(os.getenv("MAX_IMAGE_SIZE", 10 * 1024 * 1024))  # 10MB
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "heic", "webp"}
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/heic", "image/webp"}

# Ensure upload directory exists
os.makedirs(UPLOAD_DIR, exist_ok=True)


class ImageValidationError(Exception):
    """Raised when image validation fails."""
    pass


def validate_image(file_content: bytes, filename: str) -> None:
    """
    Validate uploaded image.

    Args:
        file_content: Raw file bytes
        filename: Original filename

    Raises:
        ImageValidationError: If validation fails
    """
    # Check file size
    if len(file_content) > MAX_FILE_SIZE:
        raise ImageValidationError(
            f"File too large. Maximum size: {MAX_FILE_SIZE / 1024 / 1024}MB"
        )

    # Check extension
    ext = Path(filename).suffix.lower().lstrip('.')
    if ext not in ALLOWED_EXTENSIONS:
        raise ImageValidationError(
            f"Invalid file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    # Verify it's actually an image (magic bytes check)
    image_type = imghdr.what(None, h=file_content)
    if image_type not in {'jpeg', 'png', 'webp'}:
        # Note: HEIC not supported by imghdr, but we'll allow it
        if ext != 'heic':
            raise ImageValidationError(
                "File does not appear to be a valid image"
            )


def save_image(file_content: bytes, filename: str) -> str:
    """
    Save uploaded image to temporary storage.

    Args:
        file_content: Raw file bytes
        filename: Original filename

    Returns:
        Relative path to saved file

    Raises:
        ImageValidationError: If validation fails
    """
    # Validate first
    validate_image(file_content, filename)

    # Generate unique filename
    ext = Path(filename).suffix.lower()
    unique_filename = f"{uuid.uuid4()}{ext}"
    file_path = Path(UPLOAD_DIR) / unique_filename

    # Save file
    with open(file_path, 'wb') as f:
        f.write(file_content)

    # Return relative path
    return str(file_path)


def encode_image_base64(file_path: str) -> str:
    """
    Encode image as base64 for Vision API.

    Args:
        file_path: Path to image file

    Returns:
        Base64-encoded image string
    """
    with open(file_path, 'rb') as f:
        return base64.b64encode(f.read()).decode('utf-8')


def get_image_mime_type(file_path: str) -> str:
    """
    Determine MIME type from file extension.

    Args:
        file_path: Path to image file

    Returns:
        MIME type string (e.g., 'image/jpeg')
    """
    ext = Path(file_path).suffix.lower().lstrip('.')
    mime_map = {
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'png': 'image/png',
        'heic': 'image/heic',
        'webp': 'image/webp'
    }
    return mime_map.get(ext, 'image/jpeg')


def cleanup_old_images(max_age_hours: int = 24) -> int:
    """
    Delete images older than max_age_hours.

    Args:
        max_age_hours: Maximum age in hours

    Returns:
        Number of deleted files
    """
    import time

    deleted = 0
    cutoff_time = time.time() - (max_age_hours * 3600)

    upload_path = Path(UPLOAD_DIR)
    if not upload_path.exists():
        return 0

    for file_path in upload_path.glob('*'):
        if file_path.is_file():
            if file_path.stat().st_mtime < cutoff_time:
                try:
                    file_path.unlink()
                    deleted += 1
                except Exception as e:
                    print(f"Failed to delete {file_path}: {e}")

    return deleted


def delete_image(file_path: str) -> bool:
    """
    Delete a specific image file.

    Args:
        file_path: Path to image file

    Returns:
        True if deleted, False otherwise
    """
    try:
        path = Path(file_path)
        if path.exists() and path.is_file():
            path.unlink()
            return True
    except Exception as e:
        print(f"Failed to delete {file_path}: {e}")

    return False
