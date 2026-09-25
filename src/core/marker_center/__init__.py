"""Local, confirmation-first marker-centre estimation.

The estimator deliberately does not mutate a data point.  It only returns a
candidate which a UI may preview and ask the user to confirm.

Scene coordinates follow the convention used by :mod:`src.core.precision`:
an image pixel with array index ``i`` occupies ``[i, i + 1]`` and its centre
is therefore ``i + 0.5``.  Keeping that half-pixel offset is particularly
important for even-sized rasterised markers.
"""

from src.core.marker_center.detector import estimate_marker_center
from src.core.marker_center.result import MarkerCenterResult

__all__ = ["MarkerCenterResult", "estimate_marker_center"]
