"""Authentication service for user management."""

from dataclasses import dataclass
from typing import Optional
from .jwt_handler import JWTHandler
from .models import User, Session


@dataclass
class AuthConfig:
    """Configuration for authentication service."""
    secret_key: str
    token_expiry: int = 3600
    max_attempts: int = 5


class AuthService:
    """Handles user authentication and session management."""
    
    def __init__(self, config: AuthConfig, jwt_handler: JWTHandler):
        self.config = config
        self.jwt = jwt_handler
        self._sessions: dict[str, Session] = {}
    
    def login(self, username: str, password: str) -> Session:
        """Authenticate user and create a new session.
        
        Args:
            username: The user's username.
            password: The user's password.
            
        Returns:
            A new Session object.
            
        Raises:
            AuthError: If credentials are invalid.
        """
        user = self._find_user(username)
        if user is None:
            raise AuthError(f"User not found: {username}")
        if not self._verify_password(password, user.password_hash):
            raise AuthError("Invalid password")
        token = self.jwt.create_token(user.id, self.config.token_expiry)
        session = Session(user=user, token=token)
        self._sessions[session.id] = session
        return session
    
    def logout(self, session_id: str) -> None:
        """End a user session."""
        if session_id in self._sessions:
            del self._sessions[session_id]
    
    def refresh_token(self, token: str) -> str:
        """Refresh an expired JWT token."""
        payload = self.jwt.verify_token(token)
        return self.jwt.create_token(payload["user_id"], self.config.token_expiry)
    
    def get_active_sessions(self) -> list[Session]:
        """Return all active sessions."""
        return list(self._sessions.values())
    
    def _find_user(self, username: str) -> Optional[User]:
        """Look up user by username."""
        # In real implementation, would query database
        return None
    
    def _verify_password(self, plain: str, hashed: str) -> bool:
        """Verify password against hash."""
        import hashlib
        return hashlib.sha256(plain.encode()).hexdigest() == hashed


class AuthError(Exception):
    """Raised when authentication fails."""
    pass
