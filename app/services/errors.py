import logging

from fastapi import HTTPException, status
from postgrest.exceptions import APIError

logger = logging.getLogger(__name__)


def _upstream_db_error(e: APIError) -> HTTPException:
    """502 for an unexpected database error. The detail stays in the log, not the response."""
    logger.error("database error: code=%s message=%s", e.code, e.message)
    return HTTPException(status.HTTP_502_BAD_GATEWAY, "Database error")
