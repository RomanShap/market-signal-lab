"""The .env loader: sets what is missing, never overrides, tolerates comments and quotes."""

import os

from msl.config import load_dotenv


def test_dotenv_sets_missing_and_never_overrides(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    lines = [
        "# comment",
        "",
        "MSL_TEST_A=one",
        "MSL_TEST_B='two'",
        'MSL_TEST_C="three"',
        "MSL_TEST_EMPTY=",
        "not a pair",
    ]
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setenv("MSL_TEST_A", "already-set")
    for k in ("MSL_TEST_B", "MSL_TEST_C", "MSL_TEST_EMPTY"):
        monkeypatch.delenv(k, raising=False)

    assert load_dotenv(env) == 2
    assert os.environ["MSL_TEST_A"] == "already-set"
    assert os.environ["MSL_TEST_B"] == "two"
    assert os.environ["MSL_TEST_C"] == "three"
    assert "MSL_TEST_EMPTY" not in os.environ


def test_dotenv_missing_file_is_fine(tmp_path):
    assert load_dotenv(tmp_path / "nope.env") == 0
