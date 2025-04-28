import os
import unittest
import warnings

import testscenarios
import testtools
from sqlalchemy import text

from dbtesttools.engines.postgres import PostgresContainerFixture

warnings.filterwarnings("ignore", category=UserWarning, module="urllib3")


class TestPostgresContainer(
    testscenarios.TestWithScenarios, testtools.TestCase
):
    """Test that we can bring up a Postgres container."""

    scenarios = [
        ("docker", {"podman": False}),
        ("podman", {"podman": True}),
    ]

    def setUp(self):
        self.pg_fixture = None
        super().setUp()
        if self.podman:
            os.environ["DBTESTTOOLS_USE_PODMAN"] = "1"
        else:
            os.environ.pop("DBTESTTOOLS_USE_PODMAN", None)
        try:
            fixture = PostgresContainerFixture(future=True)
            fixture.setUp()
            self.pg_fixture = fixture
        except Exception as e:
            print(f'[ERROR] Failed to start Postgres fixture: {e}')

    def tearDown(self):
        if self.pg_fixture is not None:
            if hasattr(self.pg_fixture, "engine"):
                try:
                    self.pg_fixture.engine.dispose()
                except Exception as e:
                    print(f"Warning: failed to dispose engine: {e}")
            if hasattr(self.pg_fixture, "container"):
                try:
                    self.pg_fixture.container.kill()
                except Exception as e:
                    print(f"Warning: failed to kill container: {e}")
        super().tearDown()

    def test_connection(self):
        if self.pg_fixture is None:
            self.fail("Postgres fixture was not initialized")
        # Actually test that the database is reachable
        conn = self.pg_fixture.connect()
        try:
            result = conn.execute(text("SELECT 1;"))
            value = result.scalar()
            self.assertEqual(value, 1)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
