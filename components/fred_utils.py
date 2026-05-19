"""
Deprecated shim — logic has moved to data.fred_client.
This file is kept for import-path compatibility. Use data.fred_client in new code.
"""
from data.fred_client import safe_get_series, safe_get_series_multi  # noqa: F401

__all__ = ["safe_get_series", "safe_get_series_multi"]
