from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    FALKORDB_HOST: str = "localhost"
    FALKORDB_PORT: int = 6379
    FALKORDB_GRAPH_NAME: str = "erp_kb"
    
    ADMIN_TOKEN: str = "change-me"
    GOOGLE_API_KEY: Optional[str] = None
    MCP_PORT: int = 8000
    
    EMBEDDING_MODEL: str = "models/gemini-embedding-2"
    
    OTEL_SERVICE_NAME: str = "mcp-server"
    OTEL_EXPORTER_OTLP_ENDPOINT: Optional[str] = None
    
    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
