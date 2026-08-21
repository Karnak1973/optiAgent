"""Database connection management."""

from dataclasses import dataclass


@dataclass
class DBConfig:
    host: str = "localhost"
    port: int = 5432
    database: str = "app"
    user: str = "admin"
    password: str = "secret"


class Database:
    """Manages database connections."""
    
    def __init__(self, config: DBConfig):
        self.config = config
        self._connection = None
    
    def connect(self) -> None:
        """Establish database connection."""
        self._connection = True  # Simplified
    
    def disconnect(self) -> None:
        """Close database connection."""
        self._connection = None
    
    def execute(self, query: str, params: dict | None = None) -> list[dict]:
        """Execute a database query."""
        if not self._connection:
            raise ConnectionError("Not connected to database")
        return []
    
    def is_connected(self) -> bool:
        """Check if database is connected."""
        return self._connection is not None
