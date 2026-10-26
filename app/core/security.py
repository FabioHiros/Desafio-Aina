import hashlib
import hmac

from pydantic import SecretStr


def keyed_hash(value: str, key: SecretStr) -> str:
    """SHA-256 com segredo, na forma padrão (HMAC). Determinístico e irreversível sem a chave."""
    return hmac.new(key.get_secret_value().encode(), value.encode(), hashlib.sha256).hexdigest()


class Hasher:
    def __init__(self, phone_salt: SecretStr, patient_id_salt: SecretStr) -> None:
        self._phone_salt = phone_salt
        self._patient_id_salt = patient_id_salt

    def hash_phone(self, phone: str) -> str:
        """Espera o telefone já normalizado (só dígitos), para que formatações diferentes gerem o mesmo hash."""
        return keyed_hash(phone, self._phone_salt)

    def hash_patient_id(self, patient_id: str) -> str:
        return keyed_hash(patient_id, self._patient_id_salt)
