import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings
from app.main import create_app
from app.repositories.templates import FileTemplateCatalog, TemplateLoadError
from tests.fakes import FakeClock

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"


@pytest.fixture
def templates(tmp_path: Path) -> Path:
    return Path(shutil.copytree(TEMPLATES, tmp_path / "templates"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_loads_real_templates() -> None:
    catalog = FileTemplateCatalog.load(TEMPLATES)

    phq9 = catalog.get("phq9")
    assert phq9 is not None
    assert len(phq9.questions) == 9
    assert catalog.get("unknown") is None
    assert 1 <= len(catalog.journey_tasks) <= 10


def test_new_template_is_picked_up_without_code_changes(templates: Path) -> None:
    write_json(
        templates / "protocols" / "demo.json",
        {
            "template_id": "demo",
            "name": "Demo",
            "scale": [{"value": 0, "label": "Não"}, {"value": 1, "label": "Sim"}],
            "questions": [{"id": "a", "text": "Pergunta A"}],
        },
    )
    demo = FileTemplateCatalog.load(templates).get("demo")
    assert demo is not None
    assert demo.questions[0].id == "a"


def test_invalid_template_fails_with_file_name(templates: Path) -> None:
    write_json(templates / "protocols" / "broken.json", {"template_id": "broken"})
    with pytest.raises(TemplateLoadError, match=r"broken\.json inválido"):
        FileTemplateCatalog.load(templates)


def test_template_id_must_match_file_name(templates: Path) -> None:
    data = json.loads((templates / "protocols" / "phq9.json").read_text(encoding="utf-8"))
    write_json(templates / "protocols" / "copy.json", data)
    with pytest.raises(TemplateLoadError, match="difere do nome do arquivo"):
        FileTemplateCatalog.load(templates)


def test_missing_journey_tasks_fails(templates: Path) -> None:
    (templates / "journey_tasks.json").unlink()
    with pytest.raises(TemplateLoadError, match="não encontrado"):
        FileTemplateCatalog.load(templates)


@pytest.mark.parametrize("tasks", [[], ["x" * 201]])
def test_invalid_journey_tasks_fail(templates: Path, tasks: list[str]) -> None:
    write_json(templates / "journey_tasks.json", {"tarefas": tasks})
    with pytest.raises(TemplateLoadError):
        FileTemplateCatalog.load(templates)


def test_app_does_not_start_with_an_invalid_template(templates: Path, settings: Settings, clock: FakeClock) -> None:
    write_json(templates / "protocols" / "broken.json", {"template_id": "broken"})
    with pytest.raises(TemplateLoadError):
        create_app(settings.model_copy(update={"templates_dir": templates}), clock)
