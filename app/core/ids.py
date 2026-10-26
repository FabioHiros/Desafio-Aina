from uuid import uuid4


def new_id() -> str:
    """Identificador interno aleatório (UUID4): não carrega informação sobre o paciente."""
    return str(uuid4())
