from typing import Dict, Any
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from src.auth.jwt import decode_access_token

security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "MISSING_TOKEN", "message": "Authorization bearer token is required", "details": None}},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return decode_access_token(credentials.credentials)
