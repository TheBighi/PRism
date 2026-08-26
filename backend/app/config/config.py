from functools import lru_cache
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    openrouter_api_key: str
    openrouter_model: str
    gemini_api_key: str
    gemini_model: str

    class Config:
        env_file = ".env"
        extra = "ignore"

@lru_cache
def get_settings() -> Settings:
    return Settings()