from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
import os
from config import settings

# JWT Configuration (prefer app settings, fallback to env/default)
SECRET_KEY = (
    settings.SECRET_KEY
    or os.getenv("SECRET_KEY")
    or "your-secret-key-change-in-production-kisho-router-2026"
)
ALGORITHM = "HS256"
# Longer-lived tokens for demo; override via env ACCESS_TOKEN_EXPIRE_MINUTES
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "10080"))  # 7 days

# Password hashing
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

class AuthService:
    """Authentication service for JWT tokens and API keys"""
    
    @staticmethod
    def hash_password(password: str) -> str:
        """Hash a password using bcrypt"""
        return pwd_context.hash(password)
    
    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """Verify a password against its hash"""
        return pwd_context.verify(plain_password, hashed_password)
    
    @staticmethod
    def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
        """Create a JWT access token"""
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt
    
    @staticmethod
    def verify_token(token: str) -> dict:
        """Verify and decode a JWT token"""
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            return payload
        except JWTError:
            return None
    
    @staticmethod
    def create_api_key(user_id: str, key_name: str) -> str:
        """Create an API key for a user"""
        import secrets
        # Generate a random API key
        api_key = f"sk_{secrets.token_urlsafe(32)}"
        return api_key
    
    @staticmethod
    def verify_api_key(api_key: str) -> bool:
        """Verify an API key (check against database)"""
        # This would typically check Supabase for the key
        return api_key.startswith("sk_") and len(api_key) > 10

class APIKeyManager:
    """Manage API keys for users"""
    
    def __init__(self, supabase_client):
        """Initialize with Supabase client"""
        self.supabase = supabase_client
    
    def create_key(self, user_id: str, key_name: str) -> dict:
        """Create a new API key for a user"""
        api_key = AuthService.create_api_key(user_id, key_name)
        
        try:
            response = self.supabase.table("api_keys").insert({
                "user_id": user_id,
                "key_name": key_name,
                "key_hash": AuthService.hash_password(api_key),
                "is_active": True,
                "created_at": datetime.utcnow().isoformat()
            }).execute()
            
            return {
                "id": response.data[0]['id'] if response.data else None,
                "key_name": key_name,
                "api_key": api_key,  # Return full key only on creation
                "created_at": datetime.utcnow().isoformat()
            }
        except Exception as e:
            print(f"Error creating API key: {e}")
            return None
    
    def list_keys(self, user_id: str) -> list:
        """List all API keys for a user"""
        try:
            response = self.supabase.table("api_keys").select("*").eq(
                "user_id", user_id
            ).execute()
            return response.data
        except Exception as e:
            print(f"Error listing API keys: {e}")
            return []
    
    def revoke_key(self, key_id: str) -> bool:
        """Revoke an API key"""
        try:
            self.supabase.table("api_keys").update({
                "is_active": False
            }).eq("id", key_id).execute()
            return True
        except Exception as e:
            print(f"Error revoking API key: {e}")
            return False
    
    def verify_key(self, api_key: str) -> dict:
        """Verify an API key and return user info"""
        try:
            # Get all active keys (note: in production, hash the key first)
            response = self.supabase.table("api_keys").select("*").eq(
                "is_active", True
            ).execute()
            
            for key in response.data:
                if AuthService.verify_password(api_key, key["key_hash"]):
                    return {
                        "user_id": key["user_id"],
                        "key_name": key["key_name"],
                        "is_active": key["is_active"]
                    }
            return None
        except Exception as e:
            print(f"Error verifying API key: {e}")
            return None

# Default demo users for testing
DEMO_USERS = {
    "admin": {
        "username": "admin",
        "password": "admin123",
        "full_name": "Admin User",
        "role": "admin",
        "hashed_password": pwd_context.hash("admin123")
    },
    "driver": {
        "username": "driver",
        "password": "driver123",
        "full_name": "Driver User",
        "role": "driver",
        "hashed_password": pwd_context.hash("driver123")
    }
}
