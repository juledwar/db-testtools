import warnings

import fixtures
import testtools

from dbtesttools.engines.postgres import (
    DRIVER_ENV_VAR,
    PostgresContainerFixture,
)
from dbtesttools.engines.sqlite import SqliteMemoryFixture
from dbtesttools.fixtures import DatabaseResource, SessionFixture
from dbtesttools.tests.models import ModelBase


def _make_database_resource(**kwargs):
    return DatabaseResource(ModelBase, "dbtesttools.tests.models", **kwargs)


def _make_session_fixture(**kwargs):
    return SessionFixture(object(), **kwargs)


class TestFutureDeprecated(testtools.TestCase):
    """The obsolete `future` argument is accepted but warns."""

    factories = [
        ("DatabaseResource", _make_database_resource),
        ("SessionFixture", _make_session_fixture),
        ("SqliteMemoryFixture", SqliteMemoryFixture),
        ("PostgresContainerFixture", PostgresContainerFixture),
    ]

    def setUp(self):
        super().setUp()
        self.useFixture(fixtures.EnvironmentVariable(DRIVER_ENV_VAR))

    def construct(self, factory, **kwargs):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            factory(**kwargs)
        return [w for w in caught if w.category is DeprecationWarning]

    def test_future_warns(self):
        for name, factory in self.factories:
            for value in (True, False):
                caught = self.construct(factory, future=value)
                self.assertEqual(1, len(caught), (name, value))
                self.assertIn("'future' argument", str(caught[0].message))
                # The warning should point at the caller, not db-testtools.
                self.assertEqual(__file__, caught[0].filename, name)

    def test_no_future_does_not_warn(self):
        for name, factory in self.factories:
            self.assertEqual([], self.construct(factory), name)
