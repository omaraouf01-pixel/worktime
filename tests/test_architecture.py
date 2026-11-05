import ast
from pathlib import Path

import worktime.domain


def test_domain_exports() -> None:
    expected_all = {
        "DomainError",
        "RecordLockedError",
        "Session",
        "Settlement",
        "Transaction",
        "TransactionKind",
        "ValidationError",
        "Worker",
    }
    assert set(worktime.domain.__all__) == expected_all
    for name in expected_all:
        assert hasattr(worktime.domain, name)


def test_domain_layer_dependencies() -> None:
    domain_dir = Path("src/worktime/domain").resolve()
    py_files = list(domain_dir.glob("*.py"))
    assert py_files, "No python files found in domain directory"

    forbidden_modules = {
        "PySide6",
        "sqlite3",
        "worktime.data",
        "worktime.services",
        "worktime.ui",
    }

    violations: list[str] = []

    for file_path in py_files:
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for forbidden in forbidden_modules:
                        if alias.name == forbidden or alias.name.startswith(f"{forbidden}."):
                            violations.append(f"{file_path.name}: imports {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                module_name = node.module
                for forbidden in forbidden_modules:
                    if module_name == forbidden or module_name.startswith(f"{forbidden}."):
                        violations.append(f"{file_path.name}: imports from {module_name}")

    assert not violations, f"Forbidden domain imports found: {violations}"
