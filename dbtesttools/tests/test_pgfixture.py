import unittest
import warnings

from dbtesttools.engines.postgres import PostgresContainerFixture
from sqlalchemy import text

warnings.filterwarnings("ignore", category=UserWarning, module="urllib3")


class TestPostgresContainer(unittest.TestCase):
    """Test that we can bring up a Postgres container."""

    def setUp(self):
        # Create a Postgres fixture
        self.pg_fixture = PostgresContainerFixture(future=True)
        self.pg_fixture.setUp()

    def tearDown(self):
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

    def test_connection(self):
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
