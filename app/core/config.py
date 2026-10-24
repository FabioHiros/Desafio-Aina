from pathlib import Path
from typing import Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    phone_hash_salt: SecretStr = Field(min_length=16)
    event_hash_salt: SecretStr = Field(min_length=16)
    database_url: str = "sqlite:///journey_core.db"
    log_level: str = "INFO"
    templates_dir: Path = PROJECT_ROOT / "templates"
    followup_rules_path: Path = PROJECT_ROOT / "rules" / "followup.json"

    @model_validator(mode="after")
    def salts_must_differ(self) -> Self:
        # Salts iguais fariam o vazamento de um expor os dois hashes.
        if self.phone_hash_salt.get_secret_value() == self.event_hash_salt.get_secret_value():
            raise ValueError("PHONE_HASH_SALT e EVENT_HASH_SALT devem ser diferentes")
        return self
