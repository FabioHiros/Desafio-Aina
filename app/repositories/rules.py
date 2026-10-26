from pathlib import Path

from pydantic import ValidationError

from app.models.followup import FollowupRules


class RulesLoadError(Exception):
    pass


def load_followup_rules(path: Path) -> FollowupRules:
    try:
        return FollowupRules.model_validate_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise RulesLoadError(f"arquivo não encontrado: {path}") from None
    except ValidationError as exc:
        raise RulesLoadError(f"{path.name} inválido:\n{exc}") from None
