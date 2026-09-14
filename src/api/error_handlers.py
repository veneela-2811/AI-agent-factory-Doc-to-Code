import logging
from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

logger = logging.getLogger("api_errors")


async def http_exception_handler(request: Request, exc: HTTPException):
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    
    code = "HTTP_ERROR"
    if exc.status_code == 401:
        code = "UNAUTHORIZED"
    elif exc.status_code == 403:
        code = "FORBIDDEN"
    elif exc.status_code == 404:
        code = "NOT_FOUND"
    elif exc.status_code == 409:
        code = "CONFLICT"
    elif exc.status_code == 413:
        code = "PAYLOAD_TOO_LARGE"
    elif exc.status_code == 415:
        code = "UNSUPPORTED_MEDIA_TYPE"

    envelope = {
        "error": {
            "code": code,
            "message": str(exc.detail),
            "details": None
        }
    }
    return JSONResponse(status_code=exc.status_code, content=envelope)


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    envelope = {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "Invalid request payload or query parameters",
            "details": exc.errors()
        }
    }
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=envelope)


async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled exception on {request.url.path}: {str(exc)}")
    envelope = {
        "error": {
            "code": "INTERNAL_SERVER_ERROR",
            "message": "An unexpected server error occurred",
            "details": str(exc)
        }
    }
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=envelope)
