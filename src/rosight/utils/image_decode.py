"""Decode ``sensor_msgs/Image`` and ``sensor_msgs/CompressedImage`` to PIL.

This module is independent of rclpy and Textual: the caller passes any
duck-typed object with the right attributes (``width``, ``height``,
``encoding``, ``step``, ``data``) and gets back a ``PIL.Image.Image`` ready
to hand to ``textual_image``.

Supported encodings:

* ``rgb8`` / ``bgr8`` — packed 3-byte color.
* ``rgba8`` / ``bgra8`` — packed 4-byte color.
* ``mono8`` — single-channel 8-bit grayscale.
* ``mono16`` — single-channel 16-bit; min/max normalized then mapped through
  the active colormap (default turbo) so depth-like images are readable.
* ``32FC1`` — single-channel float32 depth; non-finite values mapped to LUT
  index 0; the rest normalized.

For depth-style encodings (``mono16``, ``32FC1``) the caller picks the
colormap via ``colormap=`` (``"turbo"`` / ``"viridis"`` / ``"gray"``).
"""

from __future__ import annotations

import io
import logging
from typing import Any, Literal

import numpy as np
from PIL import Image as PILImage

log = logging.getLogger(__name__)

Colormap = Literal["turbo", "viridis", "gray"]


# Generated offline; see docs/development.md.  Each is 256 RGB triples.
_TURBO_BYTES = bytes((
    34, 23, 27, 39, 25, 39, 43, 27, 51, 47, 30, 63, 50, 32, 74, 53, 34, 84, 56, 37, 94, 59, 39, 104,
    61, 41, 113, 64, 44, 122, 65, 46, 131, 67, 49, 139, 69, 52, 147, 70, 54, 154, 71, 57, 162, 72, 59, 168,
    73, 62, 175, 73, 65, 181, 74, 67, 187, 74, 70, 192, 74, 73, 197, 74, 75, 202, 74, 78, 207, 74, 81, 211,
    74, 83, 215, 73, 86, 219, 73, 89, 222, 72, 92, 225, 71, 95, 228, 71, 97, 231, 70, 100, 234, 69, 103, 236,
    68, 106, 238, 67, 108, 240, 66, 111, 242, 65, 114, 243, 64, 117, 244, 62, 119, 245, 61, 122, 246, 60, 125, 247,
    59, 128, 248, 58, 130, 248, 57, 133, 248, 55, 136, 248, 54, 139, 248, 53, 141, 248, 52, 144, 248, 51, 147, 247,
    50, 149, 247, 48, 152, 246, 47, 155, 245, 46, 157, 244, 45, 160, 243, 44, 162, 242, 43, 165, 241, 43, 167, 239,
    42, 170, 238, 41, 172, 236, 40, 175, 235, 40, 177, 233, 39, 180, 231, 39, 182, 229, 38, 184, 228, 38, 187, 226,
    37, 189, 224, 37, 191, 221, 37, 193, 219, 37, 196, 217, 36, 198, 215, 36, 200, 213, 37, 202, 210, 37, 204, 208,
    37, 206, 206, 37, 208, 203, 37, 210, 201, 38, 212, 198, 38, 214, 196, 39, 216, 193, 40, 217, 191, 40, 219, 188,
    41, 221, 186, 42, 223, 183, 43, 224, 181, 44, 226, 178, 45, 227, 175, 46, 229, 173, 48, 230, 170, 49, 232, 168,
    50, 233, 165, 52, 235, 162, 53, 236, 160, 55, 237, 157, 57, 238, 155, 58, 240, 152, 60, 241, 150, 62, 242, 147,
    64, 243, 145, 66, 244, 142, 68, 245, 140, 70, 246, 137, 73, 246, 135, 75, 247, 132, 77, 248, 130, 79, 249, 128,
    82, 249, 125, 84, 250, 123, 87, 250, 121, 89, 251, 119, 92, 251, 116, 95, 252, 114, 97, 252, 112, 100, 252, 110,
    103, 253, 108, 106, 253, 106, 109, 253, 104, 112, 253, 102, 115, 253, 100, 117, 253, 98, 120, 253, 96, 123, 253, 94,
    126, 253, 92, 130, 253, 90, 133, 252, 89, 136, 252, 87, 139, 252, 85, 142, 251, 83, 145, 251, 82, 148, 250, 80,
    151, 250, 79, 154, 249, 77, 157, 248, 76, 160, 248, 74, 164, 247, 73, 167, 246, 71, 170, 245, 70, 173, 244, 68,
    176, 243, 67, 179, 242, 66, 182, 241, 65, 185, 240, 63, 188, 239, 62, 191, 238, 61, 194, 236, 60, 197, 235, 59,
    199, 234, 58, 202, 232, 57, 205, 231, 56, 208, 229, 55, 210, 228, 54, 213, 226, 53, 216, 224, 52, 218, 223, 51,
    221, 221, 50, 223, 219, 49, 225, 217, 49, 228, 216, 48, 230, 214, 47, 232, 212, 46, 234, 210, 46, 236, 208, 45,
    238, 206, 44, 240, 204, 44, 242, 202, 43, 244, 199, 42, 246, 197, 42, 247, 195, 41, 249, 193, 40, 250, 190, 40,
    252, 188, 39, 253, 186, 39, 254, 183, 38, 255, 181, 38, 255, 179, 37, 255, 176, 37, 255, 174, 36, 255, 171, 36,
    255, 169, 35, 255, 166, 35, 255, 163, 34, 255, 161, 34, 255, 158, 33, 255, 155, 33, 255, 153, 33, 255, 150, 32,
    255, 147, 32, 255, 145, 31, 255, 142, 31, 255, 139, 30, 255, 136, 30, 255, 134, 30, 255, 131, 29, 255, 128, 29,
    255, 125, 28, 255, 123, 28, 255, 120, 27, 255, 117, 27, 255, 114, 26, 254, 111, 26, 253, 109, 26, 252, 106, 25,
    250, 103, 25, 249, 100, 24, 247, 97, 24, 246, 95, 23, 244, 92, 23, 242, 89, 22, 240, 87, 22, 238, 84, 21,
    236, 81, 21, 234, 79, 20, 232, 76, 19, 230, 73, 19, 228, 71, 18, 225, 68, 18, 223, 66, 17, 221, 63, 17,
    218, 61, 16, 216, 58, 15, 213, 56, 15, 211, 53, 14, 208, 51, 14, 206, 49, 13, 203, 47, 12, 200, 44, 12,
    198, 42, 11, 195, 40, 10, 192, 38, 10, 190, 36, 9, 187, 34, 8, 185, 32, 8, 182, 31, 7, 179, 29, 6,
    177, 27, 6, 174, 26, 5, 172, 24, 4, 170, 23, 4, 167, 21, 3, 165, 20, 2, 163, 19, 2, 161, 17, 1,
    159, 16, 0, 157, 15, 0, 155, 15, 0, 153, 14, 0, 151, 13, 0, 150, 12, 0, 149, 12, 0, 147, 12, 0,
    146, 11, 0, 145, 11, 0, 145, 11, 0, 144, 11, 0, 144, 11, 0, 144, 11, 0, 144, 12, 0, 144, 12, 0,
))

_VIRIDIS_BYTES = bytes((
    68, 1, 83, 67, 2, 85, 66, 4, 86, 65, 5, 87, 65, 6, 89, 64, 8, 90, 64, 9, 91, 63, 10, 93,
    62, 12, 94, 62, 13, 95, 61, 15, 96, 61, 16, 97, 60, 17, 98, 60, 19, 99, 59, 20, 101, 59, 22, 102,
    58, 23, 103, 58, 24, 104, 57, 26, 105, 57, 27, 106, 56, 29, 107, 56, 30, 108, 56, 31, 109, 55, 33, 109,
    55, 34, 110, 55, 35, 111, 54, 37, 112, 54, 38, 113, 54, 39, 114, 53, 41, 115, 53, 42, 116, 53, 44, 116,
    53, 45, 117, 52, 46, 118, 52, 48, 119, 52, 49, 119, 52, 50, 120, 52, 52, 121, 51, 53, 122, 51, 54, 122,
    51, 55, 123, 51, 57, 124, 51, 58, 124, 51, 59, 125, 50, 61, 126, 50, 62, 126, 50, 63, 127, 50, 64, 127,
    50, 66, 128, 50, 67, 129, 50, 68, 129, 50, 69, 130, 50, 71, 130, 50, 72, 131, 49, 73, 131, 49, 74, 132,
    49, 76, 132, 49, 77, 133, 49, 78, 133, 49, 79, 134, 49, 80, 134, 49, 81, 135, 49, 83, 135, 49, 84, 136,
    49, 85, 136, 49, 86, 137, 49, 87, 137, 49, 88, 137, 49, 89, 138, 49, 91, 138, 49, 92, 139, 49, 93, 139,
    49, 94, 140, 49, 95, 140, 49, 96, 140, 49, 97, 141, 49, 98, 141, 49, 99, 141, 49, 100, 142, 49, 101, 142,
    49, 102, 142, 49, 103, 143, 49, 104, 143, 49, 105, 143, 49, 106, 144, 49, 107, 144, 49, 108, 144, 49, 109, 145,
    49, 110, 145, 49, 111, 145, 49, 112, 146, 49, 113, 146, 49, 114, 146, 49, 115, 146, 49, 116, 147, 50, 116, 147,
    50, 117, 147, 50, 118, 148, 50, 119, 148, 50, 120, 148, 50, 121, 148, 50, 121, 149, 50, 122, 149, 50, 123, 149,
    50, 124, 149, 50, 125, 150, 50, 125, 150, 50, 126, 150, 50, 127, 150, 50, 128, 150, 50, 128, 151, 50, 129, 151,
    50, 130, 151, 50, 131, 151, 50, 131, 151, 50, 132, 152, 50, 133, 152, 50, 133, 152, 50, 134, 152, 50, 135, 152,
    50, 135, 153, 50, 136, 153, 50, 137, 153, 50, 137, 153, 50, 138, 153, 50, 138, 153, 50, 139, 153, 50, 140, 154,
    50, 140, 154, 50, 141, 154, 50, 141, 154, 50, 142, 154, 50, 142, 154, 50, 143, 154, 50, 143, 155, 50, 144, 155,
    50, 144, 155, 50, 145, 155, 50, 145, 155, 50, 146, 155, 49, 146, 155, 49, 147, 155, 49, 147, 155, 49, 147, 156,
    49, 148, 156, 49, 148, 156, 49, 149, 156, 49, 149, 156, 49, 149, 156, 49, 150, 156, 49, 150, 156, 49, 150, 156,
    49, 151, 156, 49, 151, 156, 49, 151, 156, 48, 152, 157, 48, 152, 157, 48, 152, 157, 48, 153, 157, 48, 153, 157,
    48, 153, 157, 48, 153, 157, 48, 154, 157, 48, 154, 157, 47, 154, 157, 47, 154, 157, 47, 154, 157, 47, 155, 157,
    47, 155, 157, 47, 155, 157, 47, 155, 157, 47, 155, 157, 46, 156, 157, 46, 156, 157, 46, 156, 157, 46, 156, 157,
    46, 156, 157, 46, 156, 157, 45, 156, 157, 45, 156, 157, 45, 156, 157, 45, 156, 157, 45, 157, 157, 45, 157, 157,
    44, 157, 157, 44, 157, 157, 44, 157, 157, 44, 157, 157, 44, 157, 157, 43, 157, 157, 43, 157, 156, 43, 157, 156,
    43, 157, 156, 43, 157, 156, 42, 157, 156, 42, 157, 156, 42, 157, 156, 42, 156, 156, 42, 156, 156, 41, 156, 156,
    41, 156, 156, 41, 156, 156, 41, 156, 156, 40, 156, 155, 40, 156, 155, 40, 156, 155, 40, 155, 155, 40, 155, 155,
    39, 155, 155, 39, 155, 155, 39, 155, 155, 39, 155, 155, 38, 154, 154, 38, 154, 154, 38, 154, 154, 37, 154, 154,
    37, 154, 154, 37, 153, 154, 37, 153, 154, 36, 153, 153, 36, 153, 153, 36, 152, 153, 36, 152, 153, 35, 152, 153,
    35, 151, 153, 35, 151, 153, 34, 151, 152, 34, 150, 152, 34, 150, 152, 34, 150, 152, 33, 149, 152, 33, 149, 152,
    33, 149, 151, 32, 148, 151, 32, 148, 151, 32, 148, 151, 31, 147, 151, 31, 147, 151, 31, 146, 150, 30, 146, 150,
    30, 145, 150, 30, 145, 150, 29, 145, 150, 29, 144, 149, 29, 144, 149, 28, 143, 149, 28, 143, 149, 28, 142, 149,
    27, 142, 149, 27, 141, 148, 27, 141, 148, 26, 140, 148, 26, 140, 148, 26, 139, 148, 25, 139, 148, 25, 138, 147,
))

TURBO_LUT: np.ndarray = np.frombuffer(_TURBO_BYTES, dtype=np.uint8).reshape(256, 3)
VIRIDIS_LUT: np.ndarray = np.frombuffer(_VIRIDIS_BYTES, dtype=np.uint8).reshape(256, 3)


def _lut(name: Colormap) -> np.ndarray:
    if name == "turbo":
        return TURBO_LUT
    if name == "viridis":
        return VIRIDIS_LUT
    # gray: identity
    g = np.arange(256, dtype=np.uint8)
    return np.stack([g, g, g], axis=1)


def _to_bytes(data: Any) -> bytes:
    """Coerce msg.data (which can be bytes, list[int], or array.array) to bytes."""
    if isinstance(data, (bytes, bytearray, memoryview)):
        return bytes(data)
    return bytes(bytearray(data))


def _apply_colormap(values_uint8: np.ndarray, colormap: Colormap) -> np.ndarray:
    lut = _lut(colormap)
    return lut[values_uint8]


def _normalize_float(arr: np.ndarray) -> np.ndarray:
    """Return uint8 normalized to [0, 255]; non-finite mapped to 0."""
    finite = np.isfinite(arr)
    if not finite.any():
        return np.zeros(arr.shape, dtype=np.uint8)
    valid = arr[finite]
    lo = float(valid.min())
    hi = float(valid.max())
    if hi - lo < 1e-9:
        return np.zeros(arr.shape, dtype=np.uint8)
    out = np.zeros(arr.shape, dtype=np.uint8)
    norm = ((arr - lo) / (hi - lo) * 255.0).clip(0, 255)
    out[finite] = norm[finite].astype(np.uint8)
    return out


def decode_image(msg: Any, colormap: Colormap = "turbo") -> PILImage.Image | None:
    """Decode a ``sensor_msgs/Image``-shaped message to a PIL image.

    Returns ``None`` if the encoding is unsupported (logged at debug).
    """
    encoding = (getattr(msg, "encoding", "") or "").lower().strip()
    width = int(getattr(msg, "width", 0))
    height = int(getattr(msg, "height", 0))
    if width <= 0 or height <= 0:
        return None
    raw = _to_bytes(getattr(msg, "data", b""))

    try:
        if encoding == "rgb8":
            arr = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 3)
            return PILImage.fromarray(arr, mode="RGB")
        if encoding == "bgr8":
            arr = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 3)
            return PILImage.fromarray(arr[..., ::-1].copy(), mode="RGB")
        if encoding == "rgba8":
            arr = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 4)
            return PILImage.fromarray(arr, mode="RGBA")
        if encoding == "bgra8":
            arr = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 4)
            swapped = arr[..., [2, 1, 0, 3]].copy()
            return PILImage.fromarray(swapped, mode="RGBA")
        if encoding == "mono8":
            arr = np.frombuffer(raw, dtype=np.uint8).reshape(height, width)
            return PILImage.fromarray(arr, mode="L")
        if encoding == "mono16":
            arr16 = np.frombuffer(raw, dtype=np.uint16).reshape(height, width)
            # Map zeros (often "no return") to non-finite-like behavior:
            # exclude them from min/max so they don't compress the dynamic range.
            arr_f = arr16.astype(np.float32)
            arr_f[arr16 == 0] = np.nan
            u8 = _normalize_float(arr_f)
            rgb = _apply_colormap(u8, colormap)
            return PILImage.fromarray(rgb, mode="RGB")
        if encoding in {"32fc1", "32fc"}:
            arr_f = np.frombuffer(raw, dtype=np.float32).reshape(height, width)
            u8 = _normalize_float(arr_f)
            rgb = _apply_colormap(u8, colormap)
            return PILImage.fromarray(rgb, mode="RGB")
    except Exception:
        log.exception("decode_image failed for encoding=%r %dx%d", encoding, width, height)
        return None

    log.debug("decode_image: unsupported encoding %r", encoding)
    return None


def decode_compressed_image(msg: Any) -> PILImage.Image | None:
    """Decode a ``sensor_msgs/CompressedImage`` via Pillow (sniffs the format)."""
    raw = _to_bytes(getattr(msg, "data", b""))
    if not raw:
        return None
    try:
        img = PILImage.open(io.BytesIO(raw))
        img.load()  # force decode now while the BytesIO is still alive
        return img
    except Exception:
        log.exception("decode_compressed_image failed")
        return None
