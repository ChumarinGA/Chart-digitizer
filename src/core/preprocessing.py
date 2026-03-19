"""Image pre-processing utilities used by various pipeline stages."""

from __future__ import annotations

import cv2
import numpy as np


def to_grayscale(img: np.ndarray) -> np.ndarray:
    if len(img.shape) == 2:
        return img
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def to_hsv(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2HSV)


def to_lab(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2LAB)


def denoise(img: np.ndarray, strength: int = 10) -> np.ndarray:
    if len(img.shape) == 3:
        return cv2.fastNlMeansDenoisingColored(img, None, strength, strength, 7, 21)
    return cv2.fastNlMeansDenoising(img, None, strength, 7, 21)


def enhance_contrast(img: np.ndarray, clip_limit: float = 2.0, tile_size: int = 8) -> np.ndarray:
    """Apply CLAHE contrast enhancement.  Works on grayscale or the L-channel of a color image."""
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(tile_size, tile_size))
    if len(img.shape) == 2:
        return clahe.apply(img)
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    lab[:, :, 0] = clahe.apply(lab[:, :, 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def binarize(img: np.ndarray, method: str = "otsu", invert: bool = False) -> np.ndarray:
    """Return a binary mask (0/255).

    method: 'otsu' | 'adaptive'
    """
    gray = to_grayscale(img)
    if method == "adaptive":
        mask = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 15, 8
        )
    else:
        _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    if invert:
        mask = cv2.bitwise_not(mask)
    return mask


def morphological_clean(mask: np.ndarray, kernel_size: int = 3, iterations: int = 1) -> np.ndarray:
    """Remove small noise by morphological opening."""
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
    cleaned = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=iterations)
    return cleaned


def detect_edges(img: np.ndarray, low: int = 50, high: int = 150) -> np.ndarray:
    gray = to_grayscale(img)
    return cv2.Canny(gray, low, high, apertureSize=3)
