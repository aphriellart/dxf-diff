"""dxf-diff - visual diff for AutoCAD DXF/DWG drawings."""

__version__ = "0.1.0"

from .core import Change, DiffResult, diff, load  # noqa: E402

__all__ = ["diff", "load", "DiffResult", "Change", "__version__"]
