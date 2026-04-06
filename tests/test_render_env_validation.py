import logging
import os
import unittest
from unittest.mock import patch

from render_env_validation import DEFAULT_SECRET_KEY_PLACEHOLDER, validate_render_environment


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _base_render_env(**overrides: str) -> dict[str, str]:
    env: dict[str, str] = {
        "RENDER": "1",
        "SECRET_KEY": "not-the-placeholder-use-strong-random-secret",
        "IMPORT_AUTH_PASSWORD": "import-shared-secret",
        "APP_BASE_URL": "https://example.onrender.com",
        "ADMIN_PASS": "Str0ng_local_only_not_default",
    }
    env.update(overrides)
    return env


class ValidateRenderEnvironmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.handler = _ListHandler()
        self.log = logging.getLogger("test_render_env_validation")
        self.log.setLevel(logging.DEBUG)
        self.log.handlers.clear()
        self.log.addHandler(self.handler)

    def tearDown(self) -> None:
        self.log.removeHandler(self.handler)

    def test_when_not_render_does_nothing(self) -> None:
        with patch.dict(os.environ, _base_render_env(RENDER=""), clear=False):
            validate_render_environment(self.log)
        self.assertEqual(self.handler.records, [])

    def test_placeholder_secret_critical_no_exception(self) -> None:
        with patch.dict(
            os.environ,
            _base_render_env(SECRET_KEY=DEFAULT_SECRET_KEY_PLACEHOLDER),
            clear=False,
        ):
            validate_render_environment(self.log)
        self.assertTrue(any(r.levelno == logging.CRITICAL for r in self.handler.records))
        self.assertTrue(any("SECRET_KEY" in r.getMessage() for r in self.handler.records))

    def test_empty_import_auth_password_critical_no_exception(self) -> None:
        with patch.dict(os.environ, _base_render_env(IMPORT_AUTH_PASSWORD=""), clear=False):
            validate_render_environment(self.log)
        self.assertTrue(any(r.levelno == logging.CRITICAL for r in self.handler.records))
        self.assertTrue(any("IMPORT_AUTH_PASSWORD" in r.getMessage() for r in self.handler.records))

    def test_empty_app_base_url_logs_warning_no_exception(self) -> None:
        with patch.dict(os.environ, _base_render_env(APP_BASE_URL=""), clear=False):
            validate_render_environment(self.log)
        self.assertTrue(any(r.levelno == logging.WARNING for r in self.handler.records))
        self.assertTrue(any("APP_BASE_URL" in r.getMessage() for r in self.handler.records))

    def test_http_app_base_url_logs_warning(self) -> None:
        with patch.dict(os.environ, _base_render_env(APP_BASE_URL="http://insecure.example.com"), clear=False):
            validate_render_environment(self.log)
        self.assertTrue(any("https://" in r.getMessage() for r in self.handler.records))

    def test_weak_admin_pass_critical(self) -> None:
        with patch.dict(os.environ, _base_render_env(ADMIN_PASS="admin123"), clear=False):
            validate_render_environment(self.log)
        self.assertTrue(any("ADMIN_PASS" in r.getMessage() for r in self.handler.records))


if __name__ == "__main__":
    unittest.main()
