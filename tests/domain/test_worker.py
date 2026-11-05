from dataclasses import FrozenInstanceError

import pytest

from worktime.domain.errors import ValidationError
from worktime.domain.worker import Worker


def test_worker_valid() -> None:
    worker = Worker(
        name="Omar",
        phone="0555123456",
        note="Part-time cashier",
        archived=False,
        id=1,
    )
    assert worker.name == "Omar"
    assert worker.phone == "0555123456"
    assert worker.note == "Part-time cashier"
    assert worker.archived is False
    assert worker.id == 1


def test_worker_name_stripped() -> None:
    worker = Worker(name="  Fatima Zahra  ", phone="  123  ", note="  test note  ")
    assert worker.name == "Fatima Zahra"
    assert worker.phone == "123"
    assert worker.note == "test note"


def test_worker_arabic_name_accepted() -> None:
    worker = Worker(name="أحمد بن محمد", note="ملاحظة تجريبية")
    assert worker.name == "أحمد بن محمد"
    assert worker.note == "ملاحظة تجريبية"


@pytest.mark.parametrize(
    "invalid_name",
    [
        "",
        "   ",
        "\t\n",
        "a" * 101,
        "   " + "b" * 101 + "   ",
    ],
)
def test_worker_invalid_name_rejected(invalid_name: str) -> None:
    with pytest.raises(ValidationError):
        Worker(name=invalid_name)


def test_worker_non_str_name_rejected() -> None:
    with pytest.raises(ValidationError):
        Worker(name=123)  # type: ignore[arg-type]


def test_worker_phone_too_long_rejected() -> None:
    with pytest.raises(ValidationError):
        Worker(name="Omar", phone="1" * 31)


def test_worker_note_too_long_rejected() -> None:
    with pytest.raises(ValidationError):
        Worker(name="Omar", note="n" * 501)


@pytest.mark.parametrize("invalid_archived", [1, 0, "true", "False", None])
def test_worker_non_bool_archived_rejected(invalid_archived: object) -> None:
    with pytest.raises(ValidationError):
        Worker(name="Omar", archived=invalid_archived)  # type: ignore[arg-type]


@pytest.mark.parametrize("invalid_id", [0, -1, -100, True, False, "1"])
def test_worker_invalid_id_rejected(invalid_id: object) -> None:
    with pytest.raises(ValidationError):
        Worker(name="Omar", id=invalid_id)  # type: ignore[arg-type]


def test_worker_is_frozen() -> None:
    worker = Worker(name="Omar")
    with pytest.raises(FrozenInstanceError):
        worker.name = "Ali"  # type: ignore[misc]
