"""Image normalisation and local-window helpers for marker detection."""

from __future__ import annotations

import numpy as np


def normalised_features(image: np.ndarray) -> np.ndarray:
    """Return finite ``H x W x C`` colour features on a 0..255 scale."""
    array = np.asarray(image)
    if array.size == 0 or array.ndim not in (2, 3):
        raise ValueError("image must be a non-empty grayscale, BGR, or BGRA array")
    if array.ndim == 3 and array.shape[2] not in (1, 3, 4):
        raise ValueError("image must be a grayscale, BGR, or BGRA array")

    values = array.astype(np.float64, copy=False)
    if not np.all(np.isfinite(values)):
        raise ValueError("image must contain only finite values")
    if values.ndim == 2:
        values = values[:, :, None]
    elif values.shape[2] == 4:
        values = values[:, :, :3]

    minimum = float(np.min(values))
    maximum = float(np.max(values))
    if minimum < 0.0:
        raise ValueError("image values must be non-negative")
    if maximum <= 1.5:
        values = values * 255.0
    elif maximum > 255.0:
        # Use the observed image range: this supports both full-range uint16
        # scans and 10/12-bit data stored in a uint16 container.
        values = values * (255.0 / maximum)
    return np.clip(values, 0.0, 255.0)


def border_mask(height: int, width: int) -> np.ndarray:
    """Select a robust background-sampling band around a local patch."""
    band = max(2, int(round(min(height, width) * 0.12)))
    mask = np.zeros((height, width), dtype=bool)
    mask[:band, :] = True
    mask[-band:, :] = True
    mask[:, :band] = True
    mask[:, -band:] = True
    return mask
