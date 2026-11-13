"""Architectural and boundary tests for the services layer."""

import ast
from pathlib import Path

import worktime.services


def _get_service_files() -> list[Path]:
    services_dir = Path("src/worktime/services").resolve()
    py_files = sorted(services_dir.glob("*.py"))
    assert py_files, "No python files found in services directory"
    return py_files


def test_services_exports() -> None:
    expected_all = {
        "AttendanceService",
        "Clock",
        "DatabaseError",
        "DuplicateWorkerError",
        "ManualEntry",
        "NoOpenSessionError",
        "OpenSessionExistsError",
        "RecordNotFoundError",
        "ServiceError",
        "SessionOverlapError",
        "TransactionService",
        "TransactionTotals",
        "WorkerArchivedError",
        "WorkerHasOpenSessionError",
        "WorkerService",
        "WorkerSummary",
        "system_clock",
    }
    assert set(worktime.services.__all__) == expected_all
    assert len(worktime.services.__all__) == 17
    for name in expected_all:
        assert hasattr(worktime.services, name)
    assert "_rules" not in worktime.services.__all__


def test_services_layer_dependencies() -> None:
    forbidden_modules = {"PySide6", "worktime.ui"}
    allowed_worktime_prefixes = (
        "worktime.domain",
        "worktime.data",
        "worktime.services",
    )
    violations: list[str] = []

    for file_path in _get_service_files():
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))

        # Check imports
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for forbidden in forbidden_modules:
                        if alias.name == forbidden or alias.name.startswith(forbidden + "."):
                            violations.append(f"{file_path.name}: imports {alias.name}")
                    if alias.name.startswith("worktime.") and not any(
                        alias.name.startswith(prefix) for prefix in allowed_worktime_prefixes
                    ):
                        violations.append(f"{file_path.name}: invalid worktime import {alias.name}")

            elif isinstance(node, ast.ImportFrom) and node.module:
                module_name = node.module
                for forbidden in forbidden_modules:
                    if module_name == forbidden or module_name.startswith(forbidden + "."):
                        violations.append(f"{file_path.name}: imports from {module_name}")
                if module_name.startswith("worktime.") and not any(
                    module_name.startswith(prefix) for prefix in allowed_worktime_prefixes
                ):
                    violations.append(f"{file_path.name}: invalid worktime import {module_name}")

            # Check no call to execute or executemany
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in ("execute", "executemany"):
                    violations.append(
                        f"{file_path.name}:{node.lineno}: calls forbidden method {node.func.attr}"
                    )

            # Check no sqlite3 call
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                    if node.func.value.id == "sqlite3":
                        violations.append(f"{file_path.name}:{node.lineno}: calls sqlite3 directly")
                elif isinstance(node.func, ast.Name) and "sqlite3" in node.func.id:
                    violations.append(f"{file_path.name}:{node.lineno}: calls sqlite3 directly")

            # Check no sqlite3 except handler
            if isinstance(node, ast.ExceptHandler) and node.type is not None:
                for sub_node in ast.walk(node.type):
                    if isinstance(sub_node, ast.Name) and "sqlite3" in sub_node.id:
                        violations.append(f"{file_path.name}:{node.lineno}: catches sqlite3 error")
                    elif isinstance(sub_node, ast.Attribute) and (
                        (isinstance(sub_node.value, ast.Name) and sub_node.value.id == "sqlite3")
                        or "sqlite3" in sub_node.attr
                    ):
                        violations.append(f"{file_path.name}:{node.lineno}: catches sqlite3 error")

        # Check sqlite3 import only under if TYPE_CHECKING: or solely in annotations
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "sqlite3":
                        violations.append(
                            f"{file_path.name}:{node.lineno}: "
                            "sqlite3 imported outside TYPE_CHECKING"
                        )
            elif isinstance(node, ast.ImportFrom) and node.module == "sqlite3":
                violations.append(
                    f"{file_path.name}:{node.lineno}: sqlite3 imported outside TYPE_CHECKING"
                )

    assert not violations, "Services architectural violations found:\n" + "\n".join(violations)


def test_clock_isolation() -> None:
    violations: list[str] = []
    found_in_clock = False

    for file_path in _get_service_files():
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
        is_clock_file = file_path.name == "clock.py"

        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in ("now", "today"):
                if is_clock_file:
                    found_in_clock = True
                else:
                    violations.append(
                        f"{file_path.name}:{node.lineno}: forbidden call to datetime.{node.attr}"
                    )
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in ("now", "today"):
                        if not is_clock_file:
                            violations.append(
                                f"{file_path.name}:{node.lineno}: forbidden import of {alias.name}"
                            )

    assert found_in_clock, "datetime.now was not found in clock.py"
    assert not violations, "Direct time access violations found:\n" + "\n".join(violations)
