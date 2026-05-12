from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    FALKORDB_HOST: str = "localhost"
    FALKORDB_PORT: int = 6379
    FALKORDB_GRAPH_NAME: str = "erp_kb"
    
    GITHUB_REPO_URL: Optional[str] = None
    GITHUB_TOKEN: Optional[str] = None
    GOOGLE_API_KEY: Optional[str] = None
    WIKI_PATH: str = "/app/wiki"
    
    EMBEDDING_MODEL: str = "models/gemini-embedding-2"
    
    OTEL_SERVICE_NAME: str = "indexer"
    OTEL_EXPORTER_OTLP_ENDPOINT: Optional[str] = None
    
    class Config:
        env_file = ".env"

settings = Settings()
