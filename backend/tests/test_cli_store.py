import os
from pathlib import Path

import pytest

os.environ["MUZTOOLS_DATA"] = str(Path("/tmp/muztools-test-data"))

from muztool import config, store  # noqa: E402
from muztool.cli import main  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setenv("MUZTOOLS_DATA", str(tmp_path))
    config.DATA_DIR = tmp_path
    config.SECRET_FILE = tmp_path / "secret.key"
    store.DATA_DIR = tmp_path
    store.ensure_dirs = config.ensure_dirs
    config.ensure_dirs()
    yield tmp_path


def test_register_and_approve(tmp_path, capsys):
    user = store.create_user("alice", "secret", "Alice")
    user["student"]["student_id"] = "25371537"
    user["student"]["real_name"] = "测试"
    user["student"]["status"] = "pending"
    store.save_user(user)

    main(["pending"])
    out = capsys.readouterr().out
    assert "25371537" in out

    main(["approve", "alice"])
    reloaded = store.find_user_by_username("alice")
    assert reloaded["student"]["status"] == "approved"

    main(["enable-signin", "alice"])
    reloaded = store.find_user_by_username("alice")
    assert reloaded["student"]["auto_signin"] is True


from muztool.security import validate_password, validate_username
import pytest


def test_username_and_password_rules():
    assert validate_username("alice_1") == "alice_1"
    with pytest.raises(ValueError):
        validate_username("abc")
    with pytest.raises(ValueError):
        validate_password("abcdef")
    assert validate_password("Abcdef1") == "Abcdef1"
