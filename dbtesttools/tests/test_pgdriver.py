import sys
import types

import fixtures
import testtools

from dbtesttools.engines import postgres
from dbtesttools.engines.postgres import (
    DRIVER_ENV_VAR,
    PostgresContainerFixture,
    resolve_driver,
)

_MISSING = object()


def _restore_module(name, original):
    if original is _MISSING:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = original


class TestResolveDriver(testtools.TestCase):
    """Test selection of the Postgres DB-API driver."""

    def setUp(self):
        super().setUp()
        self.useFixture(fixtures.EnvironmentVariable(DRIVER_ENV_VAR))

    def hide_modules(self, *names):
        """Make importing any of `names` raise ImportError."""
        for name in names:
            original = sys.modules.get(name, _MISSING)
            sys.modules[name] = None
            self.addCleanup(_restore_module, name, original)

    def test_explicit_psycopg2(self):
        driver = resolve_driver("psycopg2")
        self.assertEqual("psycopg2", driver.name)
        self.assertEqual("psycopg2", driver.module.__name__)
        self.assertEqual("postgresql+psycopg2", driver.url_scheme)

    def test_explicit_psycopg(self):
        driver = resolve_driver("psycopg")
        self.assertEqual("psycopg", driver.name)
        self.assertEqual("psycopg", driver.module.__name__)
        self.assertEqual("postgresql+psycopg", driver.url_scheme)

    def test_psycopg3_alias(self):
        self.assertEqual("psycopg", resolve_driver("psycopg3").name)

    def test_name_is_case_insensitive(self):
        self.assertEqual("psycopg", resolve_driver(" Psycopg3 ").name)

    def test_env_var(self):
        self.useFixture(
            fixtures.EnvironmentVariable(DRIVER_ENV_VAR, "psycopg")
        )
        self.assertEqual("psycopg", resolve_driver().name)

    def test_empty_env_var_autodetects(self):
        self.useFixture(fixtures.EnvironmentVariable(DRIVER_ENV_VAR, ""))
        self.assertEqual("psycopg2", resolve_driver().name)

    def test_explicit_arg_beats_env_var(self):
        self.useFixture(
            fixtures.EnvironmentVariable(DRIVER_ENV_VAR, "psycopg")
        )
        self.assertEqual("psycopg2", resolve_driver("psycopg2").name)

    def test_autodetect_prefers_psycopg2(self):
        self.assertEqual("psycopg2", resolve_driver().name)

    def test_autodetect_falls_back_to_psycopg(self):
        self.hide_modules("psycopg2")
        self.assertEqual("psycopg", resolve_driver().name)

    def test_autodetect_no_drivers(self):
        self.hide_modules("psycopg2", "psycopg")
        self.assertRaises(ImportError, resolve_driver)

    def test_unknown_driver(self):
        e = self.assertRaises(ValueError, resolve_driver, "pg8000")
        self.assertIn("pg8000", str(e))

    def test_unknown_driver_from_env_var(self):
        self.useFixture(fixtures.EnvironmentVariable(DRIVER_ENV_VAR, "nope"))
        self.assertRaises(ValueError, resolve_driver)

    def test_missing_driver_gives_install_hint(self):
        self.hide_modules("psycopg")
        e = self.assertRaises(ImportError, resolve_driver, "psycopg")
        self.assertIn("could not be imported", str(e))
        self.assertIn("db-testtools[psycopg3]", str(e))


class TestFixtureDriver(testtools.TestCase):
    """Test driver selection on the fixture without starting a container."""

    def setUp(self):
        super().setUp()
        self.useFixture(fixtures.EnvironmentVariable(DRIVER_ENV_VAR))

    def test_default_driver(self):
        self.assertEqual("psycopg2", PostgresContainerFixture().driver)

    def test_driver_arg(self):
        fixture = PostgresContainerFixture(driver="psycopg3")
        self.assertEqual("psycopg", fixture.driver)

    def test_driver_env_var(self):
        self.useFixture(
            fixtures.EnvironmentVariable(DRIVER_ENV_VAR, "psycopg")
        )
        self.assertEqual("psycopg", PostgresContainerFixture().driver)

    def make_engine(self, **kwargs):
        fixture = PostgresContainerFixture(**kwargs)
        fixture.local_port = 5432
        engine = fixture.create_engine()
        self.addCleanup(engine.dispose)
        return engine

    def test_create_engine_uses_driver_dialect(self):
        engine = self.make_engine(driver="psycopg")
        self.assertEqual("postgresql+psycopg", engine.url.drivername)

    def test_wait_for_pg_start_retries_driver_operational_error(self):
        fixture = PostgresContainerFixture(driver="psycopg")
        error = fixture._driver.module.OperationalError
        calls = []

        def flaky_connect():
            calls.append(None)
            if len(calls) < 3:
                raise error("not yet")

        self.useFixture(
            fixtures.MonkeyPatch(
                "dbtesttools.engines.postgres.retry_call",
                _no_delay(postgres.retry_call),
            )
        )
        fixture._try_pg_connect = flaky_connect
        fixture.wait_for_pg_start()
        self.assertEqual(3, len(calls))


class TestFixtureSetUpFailure(testtools.TestCase):
    """Test that a failed setUp does not leak the container."""

    def setUp(self):
        super().setUp()
        self.useFixture(fixtures.EnvironmentVariable(DRIVER_ENV_VAR))
        self.useFixture(fixtures.EnvironmentVariable("DBTESTTOOLS_USE_PODMAN"))
        self.useFixture(
            fixtures.MonkeyPatch(
                "dbtesttools.engines.postgres.docker",
                types.SimpleNamespace(from_env=lambda: None),
            )
        )
        self.killed = []
        self.fixture = PostgresContainerFixture(driver="psycopg2")
        self.fixture.pull_image = lambda: None
        self.fixture.find_free_port = lambda: None
        self.fixture.start_container = self.fake_start_container

    def fake_start_container(self):
        self.fixture.container = types.SimpleNamespace(
            kill=lambda: self.killed.append(True)
        )

    def raise_error(self):
        raise ValueError("boom")

    def test_container_killed_when_wait_fails(self):
        self.fixture.wait_for_pg_start = self.raise_error
        self.assertRaises(ValueError, self.fixture.setUp)
        self.assertEqual([True], self.killed)

    def test_container_killed_when_engine_creation_fails(self):
        self.fixture.wait_for_pg_start = lambda: None
        self.fixture.set_up_test_database = lambda: None
        self.fixture.create_engine = self.raise_error
        self.assertRaises(ValueError, self.fixture.setUp)
        self.assertEqual([True], self.killed)

    def test_original_error_raised_when_kill_fails(self):
        def bad_kill():
            raise RuntimeError("kill failed")

        self.fixture.start_container = lambda: setattr(
            self.fixture, "container", types.SimpleNamespace(kill=bad_kill)
        )
        self.fixture.wait_for_pg_start = self.raise_error
        self.assertRaises(ValueError, self.fixture.setUp)


def _no_delay(retry_call):
    def wrapper(f, *args, **kwargs):
        kwargs["delay"] = 0
        return retry_call(f, *args, **kwargs)

    return wrapper
