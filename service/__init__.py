"""FastAPI backend — owns the model, serves chat over HTTP."""

from .logging_config import get_logger, setup_logging

__all__ = ["get_logger", "setup_logging"]
