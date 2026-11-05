# WorkTime

WorkTime is a Windows-first desktop application built with Python, PySide6, and SQLite for a shop owner to track part-time workers' hours and settle their pay using an Arabic (RTL) interface.

## Setup

Create and activate a virtual environment, then install the package and development dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## Running the Application

Launch the application:

```powershell
python -m worktime
```

## Testing and Quality Checks

Run the test suite:

```powershell
pytest
```

Run linting and code formatting checks:

```powershell
ruff check .
ruff format --check .
```

Run static type checking:

```powershell
mypy src
```
