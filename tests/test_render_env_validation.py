import logging
import unittest

from render_env_validation import (
    DEFAULT_SECRET_KEY_PLACEHOLDER,
    render_platform_active,
    validate_render_environment,
)


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _good_kwargs() -> dict[str, str | bool]:
    return {
        "is_render": True,
        "secret_key": "not-the-placeholder-use-strong-random-secret",
        "default_secret_key_placeholder": DEFAULT_SECRET_KEY_PLACEHOLDER,
        "import_auth_password": "import-shared-secret",
        "app_base_url": "https://example.onrender.com",
        "admin_pass": "Str0ng_local_only_not_default",
    }


class ValidateRenderEnvironmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.handler = _ListHandler()
        self.log = logging.getLogger("test_render_env_validation")
        self.log.setLevel(logging.DEBUG)
        self.log.handlers.clear()
        self.log.addHandler(self.handler)

    def tearDown(self) -> None:
        self.log.removeHandler(self.handler)

    def _call(self, **overrides: object) -> None:
        kw = _good_kwargs()
        kw.update(overrides)
        validate_render_environment(
            self.log,
            bool(kw["is_render"]),
            str(kw["secret_key"]),
            str(kw["default_secret_key_placeholder"]),
            str(kw["import_auth_password"]),
            str(kw["app_base_url"]),
            str(kw["admin_pass"]),
        )

    def test_when_not_render_does_nothing(self) -> None:
        self._call(is_render=False)
        self.assertEqual(self.handler.records, [])

    def test_render_platform_active(self) -> None:
        self.assertTrue(render_platform_active("1"))
        self.assertTrue(render_platform_active("true"))
        self.assertFalse(render_platform_active(""))
        self.assertFalse(render_platform_active(None))

    def test_placeholder_secret_critical_no_exception(self) -> None:
        self._call(secret_key=DEFAULT_SECRET_KEY_PLACEHOLDER)
        self.assertTrue(any(r.levelno == logging.CRITICAL for r in self.handler.records))
        self.assertTrue(any("SECRET_KEY" in r.getMessage() for r in self.handler.records))

    def test_empty_secret_critical_no_exception(self) -> None:
        self._call(secret_key="")
        self.assertTrue(any(r.levelno == logging.CRITICAL for r in self.handler.records))

    def test_empty_import_auth_password_critical_no_exception(self) -> None:
        self._call(import_auth_password="")
        self.assertTrue(any(r.levelno == logging.CRITICAL for r in self.handler.records))
        self.assertTrue(any("IMPORT_AUTH_PASSWORD" in r.getMessage() for r in self.handler.records))

    def test_empty_app_base_url_logs_warning_no_exception(self) -> None:
        self._call(app_base_url="")
        self.assertTrue(any(r.levelno == logging.WARNING for r in self.handler.records))
        self.assertTrue(any("APP_BASE_URL" in r.getMessage() for r in self.handler.records))

    def test_http_app_base_url_logs_warning(self) -> None:
        self._call(app_base_url="http://insecure.example.com")
        self.assertTrue(any("https://" in r.getMessage() for r in self.handler.records))

    def test_weak_admin_pass_critical(self) -> None:
        self._call(admin_pass="admin123")
        self.assertTrue(any("ADMIN_PASS" in r.getMessage() for r in self.handler.records))


if __name__ == "__main__":
    unittest.main()
