import ast
from pathlib import Path

import worktime.data


def test_data_exports() -> None:
    expected_all = {
        "DatabaseError",
        "DatabaseVersionError",
        "DuplicateWorkerError",
        "MIGRATIONS",
        "OpenSessionExistsError",
        "RecordNotFoundError",
        "SCHEMA_VERSION",
        "SessionRepository",
        "SettlementRepository",
        "TransactionRepository",
        "WorkerRepository",
        "connect",
        "default_db_path",
        "migrate",
        "open_database",
        "write_transaction",
    }
    assert set(worktime.data.__all__) == expected_all
    for name in expected_all:
        assert hasattr(worktime.data, name)


def test_data_layer_dependencies() -> None:
    data_dir = Path("src/worktime/data").resolve()
    py_files = list(data_dir.glob("*.py"))
    assert py_files, "No python files found in data directory"

    forbidden_modules = {
        "PySide6",
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
                        if alias.name == forbidden or alias.name.startswith(forbidden + "."):
                            violations.append(file_path.name + ": imports " + alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                module_name = node.module
                for forbidden in forbidden_modules:
                    if module_name == forbidden or module_name.startswith(forbidden + "."):
                        violations.append(file_path.name + ": imports from " + module_name)

    assert not violations, "Forbidden data imports found: " + str(violations)


def test_no_sql_building_with_fstrings_or_formatting() -> None:
    data_dir = Path("src/worktime/data").resolve()
    py_files = list(data_dir.glob("*.py"))
    assert py_files, "No python files found in data directory"

    violations: list[str] = []

    for file_path in py_files:
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                violations.append(file_path.name + ": uses f-string (JoinedStr)")
            elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
                if isinstance(node.left, ast.Constant) and isinstance(node.left.value, str):
                    violations.append(file_path.name + ": uses % formatting on string")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "format" and isinstance(node.func.value, ast.Constant):
                    violations.append(file_path.name + ": uses .format() on string")

    assert not violations, "Formatting violations in data layer: " + str(violations)
