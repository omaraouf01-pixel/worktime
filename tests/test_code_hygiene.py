"""Code hygiene tests for assert statements and single-line docstrings."""

import ast
from pathlib import Path


def _get_src_files() -> list[Path]:
    src_dir = Path("src/worktime")
    return sorted(src_dir.rglob("*.py"))


def test_no_assert_in_src() -> None:
    for py_file in _get_src_files():
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        assert_nodes = [node for node in ast.walk(tree) if isinstance(node, ast.Assert)]
        assert not assert_nodes, (
            "Found assert statement in "
            + str(py_file)
            + " at lines: "
            + str([n.lineno for n in assert_nodes])
        )


def test_public_definitions_have_single_line_docstrings() -> None:
    violations: list[str] = []

    for py_file in _get_src_files():
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if not node.name.startswith("_"):
                    doc = ast.get_docstring(node)
                    if doc is None or not doc.strip():
                        violations.append(str(py_file) + ": " + node.name + " missing docstring")
                    elif "\n" in doc.strip():
                        violations.append(
                            str(py_file) + ": " + node.name + " docstring is not a single line"
                        )

                if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            if not item.name.startswith("_"):
                                method_doc = ast.get_docstring(item)
                                full_name = node.name + "." + item.name
                                if method_doc is None or not method_doc.strip():
                                    violations.append(
                                        str(py_file) + ": " + full_name + " missing docstring"
                                    )
                                elif "\n" in method_doc.strip():
                                    violations.append(
                                        str(py_file)
                                        + ": "
                                        + full_name
                                        + " docstring is not a single line"
                                    )

    assert not violations, "Docstring hygiene violations found:\n" + "\n".join(violations)
