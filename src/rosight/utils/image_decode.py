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


# 256-entry colormap LUTs, packed as hex strings (256 * 3 bytes = 1536 hex chars).
# Stored compactly so they survive ``ruff format`` unchanged. See
# ``docs/development.md`` for how to regenerate. Tests in
# ``tests/test_image_decode.py`` cover the shapes and rainbow ordering.
_TURBO_HEX = (
    "22171b2719272b1b332f1e3f32204a35225438255e3b27683d2971402c7a412e8343318b45349346"
    "369a4739a2483ba8493eaf4941b54a43bb4a46c04a49c54a4bca4a4ecf4a51d34a53d74956db4959"
    "de485ce1475fe44761e74664ea4567ec446aee436cf0426ff24172f34075f43e77f53d7af63c7df7"
    "3b80f83a82f83985f83788f8368bf8358df83490f83393f73295f73098f62f9bf52e9df42da0f32c"
    "a2f22ba5f12ba7ef2aaaee29acec28afeb28b1e927b4e727b6e526b8e426bbe225bde025bfdd25c1"
    "db25c4d924c6d724c8d525cad225ccd025cece25d0cb25d2c926d4c626d6c427d8c128d9bf28dbbc"
    "29ddba2adfb72be0b52ce2b22de3af2ee5ad30e6aa31e8a832e9a534eba235eca037ed9d39ee9b3a"
    "f0983cf1963ef29340f39142f48e44f58c46f68949f6874bf7844df8824ff98052f97d54fa7b57fa"
    "7959fb775cfb745ffc7261fc7064fc6e67fd6c6afd6a6dfd6870fd6673fd6475fd6278fd607bfd5e"
    "7efd5c82fd5a85fc5988fc578bfc558efb5391fb5294fa5097fa4f9af94d9df84ca0f84aa4f749a7"
    "f647aaf546adf444b0f343b3f242b6f141b9f03fbcef3ebfee3dc2ec3cc5eb3bc7ea3acae839cde7"
    "38d0e537d2e436d5e235d8e034dadf33dddd32dfdb31e1d931e4d830e6d62fe8d42eead22eecd02d"
    "eece2cf0cc2cf2ca2bf4c72af6c52af7c329f9c128fabe28fcbc27fdba27feb726ffb526ffb325ff"
    "b025ffae24ffab24ffa923ffa623ffa322ffa122ff9e21ff9b21ff9921ff9620ff9320ff911fff8e"
    "1fff8b1eff881eff861eff831dff801dff7d1cff7b1cff781bff751bff721afe6f1afd6d1afc6a19"
    "fa6719f96418f76118f65f17f45c17f25916f05716ee5415ec5115ea4f14e84c13e64913e44712e1"
    "4412df4211dd3f11da3d10d83a0fd5380fd3350ed0330ece310dcb2f0cc82c0cc62a0bc3280ac026"
    "0abe2409bb2208b92008b61f07b31d06b11b06ae1a05ac1804aa1704a71503a51402a31302a11101"
    "9f10009d0f009b0f00990e00970d00960c00950c00930c00920b00910b00910b00900b00900b0090"
    "0b00900c00900c00"
)

_VIRIDIS_HEX = (
    "44015343025542045641055741065940085a40095b3f0a5d3e0c5e3e0d5f3d0f603d10613c11623c"
    "13633b14653b16663a17673a1868391a69391b6a381d6b381e6c381f6d37216d37226e37236f3625"
    "70362671362772352973352a74352c74352d75342e7634307734317734327834347933357a33367a"
    "33377b33397c333a7c333b7d323d7e323e7e323f7f32407f32428032438132448132458232478232"
    "4883314983314a84314c84314d85314e85314f863150863151873153873154883155883156893157"
    "8931588931598a315b8a315c8b315d8b315e8c315f8c31608c31618d31628d31638d31648e31658e"
    "31668e31678f31688f31698f316a90316b90316c90316d91316e91316f9131709231719231729231"
    "7392317493327493327593327694327794327894327994327995327a95327b95327c95327d96327d"
    "96327e96327f96328096328097328197328297328397328397328498328598328598328698328798"
    "328799328899328999328999328a99328a99328b99328c9a328c9a328d9a328d9a328e9a328e9a32"
    "8f9a328f9b32909b32909b32919b32919b32929b31929b31939b31939b31939c31949c31949c3195"
    "9c31959c31959c31969c31969c31969c31979c31979c31979c30989d30989d30989d30999d30999d"
    "30999d30999d309a9d309a9d2f9a9d2f9a9d2f9a9d2f9b9d2f9b9d2f9b9d2f9b9d2f9b9d2e9c9d2e"
    "9c9d2e9c9d2e9c9d2e9c9d2e9c9d2d9c9d2d9c9d2d9c9d2d9c9d2d9d9d2d9d9d2c9d9d2c9d9d2c9d"
    "9d2c9d9d2c9d9d2b9d9d2b9d9c2b9d9c2b9d9c2b9d9c2a9d9c2a9d9c2a9d9c2a9c9c2a9c9c299c9c"
    "299c9c299c9c299c9c289c9b289c9b289c9b289b9b289b9b279b9b279b9b279b9b279b9b269a9a26"
    "9a9a269a9a259a9a259a9a25999a25999a2499992499992498992498992398992397992397992297"
    "982296982296982296982195982195982195972094972094972094971f93971f93971f92961e9296"
    "1e91961e91961d91961d90951d90951c8f951c8f951c8e951b8e951b8d941b8d941a8c941a8c941a"
    "8b94198b94198a93"
)

TURBO_LUT: np.ndarray = np.frombuffer(bytes.fromhex(_TURBO_HEX), dtype=np.uint8).reshape(256, 3)
VIRIDIS_LUT: np.ndarray = np.frombuffer(bytes.fromhex(_VIRIDIS_HEX), dtype=np.uint8).reshape(256, 3)


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
