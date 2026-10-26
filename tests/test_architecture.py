import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent / "app"

FORBIDDEN: dict[str, tuple[str, ...]] = {
    "models": (
        "sqlalchemy",
        "fastapi",
        "starlette",
        "app.core",
        "app.schemas",
        "app.repositories",
        "app.services",
        "app.api",
    ),
    "schemas": ("sqlalchemy", "fastapi", "starlette", "app.repositories", "app.services", "app.api"),
    "repositories": ("fastapi", "starlette", "app.schemas", "app.services", "app.api"),
    "services": (
        "fastapi",
        "starlette",
        "sqlalchemy",
        "app.schemas",
        "app.api",
        "app.repositories.patient",
        "app.repositories.event",
        "app.repositories.unit_of_work",
        "app.repositories.tables",
    ),
    "core": ("fastapi", "starlette", "app.models", "app.schemas", "app.repositories", "app.services", "app.api"),
}


def imports_of(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def layer_files() -> list[tuple[str, Path]]:
    return [(layer, path) for layer in FORBIDDEN for path in sorted((APP / layer).rglob("*.py"))]


@pytest.mark.parametrize(("layer", "path"), layer_files(), ids=lambda value: str(value).split("app/")[-1])
def test_layer_dependencies(layer: str, path: Path) -> None:
    bad = sorted(
        module
        for module in imports_of(path)
        for rule in FORBIDDEN[layer]
        if module == rule or module.startswith(f"{rule}.")
    )
    assert not bad, f"{path.relative_to(APP)} ({layer}) não pode importar: {bad}"


def test_interfaces_do_not_depend_on_sqlalchemy() -> None:
    bad = sorted(m for m in imports_of(APP / "repositories" / "interfaces.py") if m.startswith("sqlalchemy"))
    assert not bad, f"repositories/interfaces.py não pode importar SQLAlchemy: {bad}"
