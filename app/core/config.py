from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    phone_hash_salt: SecretStr
    event_hash_salt: SecretStr
    database_url: str = "sqlite:///journey_core.db"
