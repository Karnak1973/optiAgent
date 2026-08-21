"""JWT token handling utilities."""

import time
from dataclasses import dataclass


@dataclass
class TokenPayload:
    user_id: int
    expires_at: float
    issued_at: float


class JWTHandler:
    """Handles JWT token creation and verification."""
    
    def __init__(self, secret_key: str):
        self.secret_key = secret_key
    
    def create_token(self, user_id: int, expiry: int = 3600) -> str:
        """Create a new JWT token.
        
        Args:
            user_id: The user's unique identifier.
            expiry: Token expiry time in seconds.
            
        Returns:
            Encoded JWT token string.
        """
        payload = TokenPayload(
            user_id=user_id,
            expires_at=time.time() + expiry,
            issued_at=time.time()
        )
        return self._encode(payload)
    
    def verify_token(self, token: str) -> dict:
        """Verify and decode a JWT token.
        
        Raises:
            TokenError: If token is invalid or expired.
        """
        payload = self._decode(token)
        if payload.expires_at < time.time():
            raise TokenError("Token expired")
        return {"user_id": payload.user_id}
    
    def _encode(self, payload: TokenPayload) -> str:
        """Encode payload to token string."""
        # Simplified encoding for demo
        import json
        data = json.dumps({
            "user_id": payload.user_id,
            "exp": payload.expires_at,
            "iat": payload.issued_at
        })
        return data
    
    def _decode(self, token: str) -> TokenPayload:
        """Decode token string to payload."""
        import json
        data = json.loads(token)
        return TokenPayload(
            user_id=data["user_id"],
            expires_at=data["exp"],
            issued_at=data["iat"]
        )


class TokenError(Exception):
    """Raised when token operations fail."""
    pass
