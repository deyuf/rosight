"""Tests for the encoding-aware image decoder.

Synthesizes raw byte buffers for each supported encoding, runs them through
``decode_image`` / ``decode_compressed_image``, and asserts that the PIL
image has the expected size and mode.

Numpy and Pillow are runtime deps; if missing, the test module skips.
"""

from __future__ import annotations

import io

import pytest

np = pytest.importorskip("numpy")
PIL = pytest.importorskip("PIL")
from PIL import Image as PILImage

from rosight.utils.image_decode import (
    TURBO_LUT,
    VIRIDIS_LUT,
    decode_compressed_image,
    decode_image,
)


class _ImgMsg:
    """Duck-typed sensor_msgs/Image."""

    def __init__(self, width, height, encoding, data, step=None):
        self.width = width
        self.height = height
        self.encoding = encoding
        self.data = data
        self.step = step if step is not None else width


class _CompMsg:
    """Duck-typed sensor_msgs/CompressedImage."""

    def __init__(self, fmt, data):
        self.format = fmt
        self.data = data


# ----- LUT sanity -----------------------------------------------------------

def test_turbo_lut_shape_and_endpoints():
    assert TURBO_LUT.shape == (256, 3)
    assert TURBO_LUT.dtype == np.uint8
    # Turbo is a rainbow ramp: somewhere in the lower quartile blue dominates,
    # somewhere in the upper quartile red dominates. (Polynomial endpoints
    # don't quite hit the canonical dark-blue/dark-red corners.)
    lower = TURBO_LUT[:64]
    upper = TURBO_LUT[-64:]
    assert (lower[:, 2] > lower[:, 0]).any()  # blue dominates somewhere low
    assert (upper[:, 0] > upper[:, 2]).any()  # red dominates somewhere high


def test_viridis_lut_shape():
    assert VIRIDIS_LUT.shape == (256, 3)
    assert VIRIDIS_LUT.dtype == np.uint8


# ----- raw image encodings --------------------------------------------------

def test_decode_rgb8():
    h, w = 4, 6
    arr = np.arange(h * w * 3, dtype=np.uint8).reshape(h, w, 3)
    img = decode_image(_ImgMsg(w, h, "rgb8", arr.tobytes()))
    assert img is not None
    assert img.size == (w, h)
    assert img.mode == "RGB"
    # Top-left pixel should be (0,1,2)
    assert img.getpixel((0, 0)) == (0, 1, 2)


def test_decode_bgr8_swaps_channels():
    h, w = 2, 2
    arr = np.array([[[10, 20, 30], [40, 50, 60]], [[70, 80, 90], [100, 110, 120]]], dtype=np.uint8)
    img = decode_image(_ImgMsg(w, h, "bgr8", arr.tobytes()))
    assert img is not None
    assert img.mode == "RGB"
    # bgr8: stored BGR, returned RGB. First pixel B=10, G=20, R=30 → (30, 20, 10).
    assert img.getpixel((0, 0)) == (30, 20, 10)


def test_decode_rgba8():
    h, w = 3, 3
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    arr[..., 3] = 255  # fully opaque
    arr[0, 0] = (200, 100, 50, 255)
    img = decode_image(_ImgMsg(w, h, "rgba8", arr.tobytes()))
    assert img is not None
    assert img.mode == "RGBA"
    assert img.getpixel((0, 0)) == (200, 100, 50, 255)


def test_decode_bgra8_swaps_rgb_keeps_alpha():
    h, w = 1, 1
    arr = np.array([[[10, 20, 30, 200]]], dtype=np.uint8)
    img = decode_image(_ImgMsg(w, h, "bgra8", arr.tobytes()))
    assert img is not None
    assert img.mode == "RGBA"
    assert img.getpixel((0, 0)) == (30, 20, 10, 200)


def test_decode_mono8():
    h, w = 4, 4
    arr = (np.arange(h * w) * 16 % 256).astype(np.uint8).reshape(h, w)
    img = decode_image(_ImgMsg(w, h, "mono8", arr.tobytes()))
    assert img is not None
    assert img.mode == "L"
    assert img.size == (w, h)


def test_decode_mono16_to_colormap():
    h, w = 5, 5
    arr = (np.arange(h * w, dtype=np.uint16) * 1000)
    # Avoid 0 (treated as "no return") in this synthetic image.
    arr = (arr + 1).astype(np.uint16).reshape(h, w)
    img = decode_image(_ImgMsg(w, h, "mono16", arr.tobytes()), colormap="turbo")
    assert img is not None
    assert img.mode == "RGB"
    assert img.size == (w, h)


def test_decode_32fc1_with_nans_does_not_crash():
    h, w = 3, 4
    arr = np.array(
        [
            [1.0, 2.0, np.nan, 3.0],
            [4.0, np.inf, 5.0, 6.0],
            [7.0, 8.0, -np.inf, 9.0],
        ],
        dtype=np.float32,
    )
    img = decode_image(_ImgMsg(w, h, "32FC1", arr.tobytes()), colormap="viridis")
    assert img is not None
    assert img.mode == "RGB"
    assert img.size == (w, h)


def test_decode_unsupported_encoding_returns_none():
    img = decode_image(_ImgMsg(2, 2, "yuv422", b"\x00" * 8))
    assert img is None


def test_decode_bad_dimensions_returns_none():
    img = decode_image(_ImgMsg(0, 0, "rgb8", b""))
    assert img is None


def test_decode_handles_list_data():
    # Some ROS bindings deliver data as list[int] rather than bytes.
    h, w = 1, 2
    arr = np.array([[[10, 20, 30], [40, 50, 60]]], dtype=np.uint8)
    img = decode_image(_ImgMsg(w, h, "rgb8", arr.flatten().tolist()))
    assert img is not None
    assert img.getpixel((0, 0)) == (10, 20, 30)


# ----- compressed image -----------------------------------------------------

def _make_compressed_bytes(fmt="JPEG"):
    img = PILImage.new("RGB", (8, 8), color=(123, 45, 200))
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def test_decode_compressed_jpeg():
    data = _make_compressed_bytes("JPEG")
    img = decode_compressed_image(_CompMsg("jpeg", data))
    assert img is not None
    assert img.size == (8, 8)


def test_decode_compressed_png():
    data = _make_compressed_bytes("PNG")
    img = decode_compressed_image(_CompMsg("png", data))
    assert img is not None
    assert img.size == (8, 8)


def test_decode_compressed_empty_returns_none():
    img = decode_compressed_image(_CompMsg("jpeg", b""))
    assert img is None


def test_decode_compressed_garbage_returns_none():
    img = decode_compressed_image(_CompMsg("jpeg", b"not an image"))
    assert img is None
