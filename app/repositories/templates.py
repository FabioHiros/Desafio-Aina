from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.models.protocol import ProtocolTemplate


class TemplateLoadError(Exception):
    pass


class _JourneyTasksFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = ""
    tarefas: tuple[str, ...] = Field(min_length=1, max_length=10)


class FileTemplateCatalog:
    def __init__(self, protocols: dict[str, ProtocolTemplate], journey_tasks: tuple[str, ...]) -> None:
        self._protocols = protocols
        self._journey_tasks = journey_tasks

    @classmethod
    def load(cls, directory: Path) -> "FileTemplateCatalog":
        protocol_files = sorted((directory / "protocols").glob("*.json"))
        if not protocol_files:
            raise TemplateLoadError(f"nenhum template de protocolo em {directory / 'protocols'}")

        protocols: dict[str, ProtocolTemplate] = {}
        for path in protocol_files:
            template = _parse(ProtocolTemplate, path)
            if template.template_id != path.stem:
                raise TemplateLoadError(f"{path.name}: template_id '{template.template_id}' difere do nome do arquivo")
            protocols[template.template_id] = template

        tasks = _parse(_JourneyTasksFile, directory / "journey_tasks.json")
        for titulo in tasks.tarefas:
            if not 1 <= len(titulo) <= 200:
                raise TemplateLoadError("journey_tasks.json: cada tarefa deve ter de 1 a 200 caracteres")
        return cls(protocols, tasks.tarefas)

    def get(self, template_id: str) -> ProtocolTemplate | None:
        return self._protocols.get(template_id)

    @property
    def journey_tasks(self) -> tuple[str, ...]:
        return self._journey_tasks


def _parse[T: BaseModel](model: type[T], path: Path) -> T:
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise TemplateLoadError(f"arquivo não encontrado: {path}") from None
    except ValidationError as exc:
        raise TemplateLoadError(f"{path.name} inválido:\n{exc}") from None
