"""Database query builders."""

from .connection import Database
from ..auth.models import User


class UserQueries:
    """Query helpers for user operations."""
    
    def __init__(self, db: Database):
        self.db = db
    
    def find_by_username(self, username: str) -> User | None:
        """Find a user by username."""
        results = self.db.execute(
            "SELECT * FROM users WHERE username = :username",
            {"username": username}
        )
        if results:
            return User(**results[0])
        return None
    
    def find_by_id(self, user_id: int) -> User | None:
        """Find a user by ID."""
        results = self.db.execute(
            "SELECT * FROM users WHERE id = :id",
            {"id": user_id}
        )
        if results:
            return User(**results[0])
        return None
    
    def create_user(self, username: str, email: str, password_hash: str) -> User:
        """Create a new user."""
        self.db.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (:u, :e, :p)",
            {"u": username, "e": email, "p": password_hash}
        )
        return User(id=0, username=username, email=email, password_hash=password_hash)
