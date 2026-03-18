# Teammate's authentication module - mock for testing
from typing import Optional, List
from fastapi import HTTPException, Header

async def get_current_user(authorization: Optional[str] = Header(None)):
    """Mock auth dependency"""
    if not authorization:
        raise HTTPException(401, detail="Missing authorization header")
    return {"user_id": 1, "username": "demo_user"}

async def verify_internal_key(x_api_key: str = Header(None)):
    """Mock API key verification"""
    if not x_api_key:
        raise HTTPException(401, detail="Missing X-API-Key header")
    return True

def require_roles(*roles):
    """Mock role-based access control"""
    async def dependency(authorization: Optional[str] = Header(None)):
        if not authorization:
            raise HTTPException(401, detail="Missing authorization header")
        return {
            "user_id": 1, 
            "username": "demo_user",
            "roles": list(roles)
        }
    return dependency
