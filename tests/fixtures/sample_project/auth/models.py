"""Data models for authentication."""

from dataclasses import dataclass, field
import uuid


@dataclass
class User:
    id: int
    username: str
    email: str
    password_hash: str
    is_active: bool = True


@dataclass
class Session:
    user: User
    token: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    is_active: bool = True
