import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.core.logging import redact
from app.core.security import Hasher, keyed_hash

PHONE = "5511987654321"


@pytest.fixture
def hasher() -> Hasher:
    return Hasher(phone_salt=SecretStr("phone-salt-0000000"), patient_id_salt=SecretStr("event-salt-0000000"))


def test_hash_is_deterministic(hasher: Hasher) -> None:
    assert hasher.hash_phone(PHONE) == hasher.hash_phone(PHONE)


def test_hash_is_sha256_hex_and_does_not_contain_input(hasher: Hasher) -> None:
    digest = hasher.hash_phone(PHONE)
    assert len(digest) == 64
    assert PHONE not in digest


def test_different_salts_produce_different_hashes() -> None:
    assert keyed_hash(PHONE, SecretStr("salt-a")) != keyed_hash(PHONE, SecretStr("salt-b"))


def test_phone_and_patient_id_use_independent_salts(hasher: Hasher) -> None:
    # Mesmo valor, finalidades diferentes: hashes diferentes.
    assert hasher.hash_phone("same-value") != hasher.hash_patient_id("same-value")


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


@pytest.mark.parametrize(
    "text",
    ["ligar para +55 (11) 98765-4321", "telefone 5511987654321", "nasceu em 1990-05-10"],
)
def test_log_redaction_masks_phones_and_dates(text: str) -> None:
    redacted = redact(text)
    assert "[REDACTED]" in redacted
    assert "98765" not in redacted
    assert "1990" not in redacted
