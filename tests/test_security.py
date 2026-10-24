import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings

PHONE = "5511987654321"


def test_settings_reject_equal_salts() -> None:
    with pytest.raises(ValidationError, match="diferentes"):
        Settings(phone_hash_salt=SecretStr("same-salt-000000"), event_hash_salt=SecretStr("same-salt-000000"))


def test_settings_reject_short_salts() -> None:
    with pytest.raises(ValidationError):
        Settings(phone_hash_salt=SecretStr("short"), event_hash_salt=SecretStr("another-long-salt"))


def test_settings_do_not_print_salts() -> None:
    settings = Settings(phone_hash_salt=SecretStr("phone-salt-secret"), event_hash_salt=SecretStr("event-salt-secret"))
    assert "phone-salt-secret" not in repr(settings)
    assert "phone-salt-secret" not in str(settings.model_dump())
