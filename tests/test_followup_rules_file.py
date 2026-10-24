import json
from pathlib import Path

import pytest

from app.core.config import Settings
from app.main import create_app
from app.models.followup import Check, SkipReason
from app.repositories.rules import RulesLoadError, load_followup_rules
from tests.fakes import FakeClock

RULES_FILE = Path(__file__).resolve().parent.parent / "rules" / "followup.json"


def test_real_rules_match_the_specification() -> None:
    rules = load_followup_rules(RULES_FILE)

    assert rules.template_key == "checkin_adesao"
    assert [(r.check, r.reason) for r in rules.rules] == [
        (Check.TERMS_ACCEPTED, SkipReason.MISSING_CONSENT),
        (Check.PROTOCOL_COMPLETED, SkipReason.NO_COMPLETED_PROTOCOL),
        (Check.JOURNEY_ACTIVE, SkipReason.NO_ACTIVE_JOURNEY),
        (Check.HAS_ACTIVE_TASK, SkipReason.NO_ACTIVE_TASK),
        (Check.COOLDOWN, SkipReason.COOLDOWN),
    ]
    assert rules.rules[-1].params == {"hours": 72}


def test_invalid_rules_file_fails_with_file_name(tmp_path: Path) -> None:
    path = tmp_path / "followup.json"
    path.write_text(json.dumps({"template_key": "x", "rules": [{"check": "nope", "reason": "cooldown"}]}))
    with pytest.raises(RulesLoadError, match=r"followup\.json inválido"):
        load_followup_rules(path)


def test_missing_rules_file_fails(tmp_path: Path) -> None:
    with pytest.raises(RulesLoadError, match="não encontrado"):
        load_followup_rules(tmp_path / "missing.json")


def test_app_does_not_start_with_invalid_rules(tmp_path: Path, settings: Settings, clock: FakeClock) -> None:
    path = tmp_path / "followup.json"
    path.write_text("{}")
    with pytest.raises(RulesLoadError):
        create_app(settings.model_copy(update={"followup_rules_path": path}), clock)
