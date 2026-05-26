"""Structured logging with OTel trace/span correlation."""
import logging
import observability.setup as _telemetry


def get_logger(name: str) -> logging.Logger:
    """Return a logger that emits to OTel (with trace correlation) and stdout."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    handler = _telemetry.otel_handler

    if handler is not None and not any(isinstance(h, type(handler)) for h in logger.handlers):
        logger.addHandler(handler)

    if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        console.setFormatter(logging.Formatter("%(asctime)s %(name)s: %(message)s"))
        logger.addHandler(console)

    return logger
