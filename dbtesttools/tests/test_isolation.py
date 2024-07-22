import testresources
import testscenarios
import testtools
from sqlalchemy import func

from dbtesttools.fixtures import DatabaseResource, SessionFixture
from dbtesttools.tests.models import ModelBase, TestModel


class DBTestCaseSqlite(testresources.ResourcedTestCase, testtools.TestCase):
    db_fixture = DatabaseResource(
        ModelBase,
        "dbtesttools.tests.models",
        engine_fixture_name="SqliteMemoryFixture",
        future=True,
    )
    resources = [("database", db_fixture)]

    def setUp(self):
        super().setUp()
        self.session_fixture = SessionFixture(self.database, future=True)
        self.useFixture(self.session_fixture)
        self.session = self.session_fixture.session


class DBTestCasePostgres(testresources.ResourcedTestCase, testtools.TestCase):
    db_fixture = DatabaseResource(
        ModelBase,
        "dbtesttools.tests.models",
        engine_fixture_name="PostgresContainerFixture",
        future=True,
    )
    resources = [("database", db_fixture)]

    def setUp(self):
        super().setUp()
        self.session_fixture = SessionFixture(self.database, future=True)
        self.useFixture(self.session_fixture)
        self.session = self.session_fixture.session


# Use Scenarios to force a big list of tests to run that will re-use a single
# DB resource. This relies on a limited concurrency setting in
# pyproject.toml's scripts.py3 args for stestr.


class TestIsolationSqlite(testscenarios.TestWithScenarios, DBTestCaseSqlite):
    scenarios = [
        ("1", dict()),
        ("2", dict()),
        ("3", dict()),
        ("4", dict()),
        ("5", dict()),
        ("6", dict()),
        ("7", dict()),
        ("8", dict()),
        ("9", dict()),
        ("10", dict()),
        ("11", dict()),
        ("12", dict()),
        ("13", dict()),
        ("14", dict()),
        ("15", dict()),
        ("16", dict()),
        ("17", dict()),
        ("18", dict()),
        ("19", dict()),
        ("20", dict()),
        ("21", dict()),
        ("22", dict()),
        ("23", dict()),
        ("24", dict()),
        ("25", dict()),
        ("26", dict()),
        ("27", dict()),
        ("28", dict()),
        ("29", dict()),
        ("30", dict()),
    ]

    def test_isolation_1(self):
        self.assertEqual(self.session.scalar(func.count(TestModel.id)), 0)
        self.session.add(TestModel(name="test", value=1))
        self.session.commit()
        self.assertEqual(self.session.scalar(func.count(TestModel.id)), 1)

    def test_isolation_2(self):
        self.assertEqual(self.session.scalar(func.count(TestModel.id)), 0)
        self.session.add(TestModel(name="test", value=1))
        self.session.commit()
        self.assertEqual(self.session.scalar(func.count(TestModel.id)), 1)


class TestIsolationPostrgres(
    testscenarios.TestWithScenarios, DBTestCasePostgres
):
    scenarios = [
        ("1", dict()),
        ("2", dict()),
        ("3", dict()),
        ("4", dict()),
        ("5", dict()),
        ("6", dict()),
        ("7", dict()),
        ("8", dict()),
        ("9", dict()),
        ("10", dict()),
        ("11", dict()),
        ("12", dict()),
        ("13", dict()),
        ("14", dict()),
        ("15", dict()),
        ("16", dict()),
        ("17", dict()),
        ("18", dict()),
        ("19", dict()),
        ("20", dict()),
        ("21", dict()),
        ("22", dict()),
        ("23", dict()),
        ("24", dict()),
        ("25", dict()),
        ("26", dict()),
        ("27", dict()),
        ("28", dict()),
        ("29", dict()),
        ("30", dict()),
    ]

    def test_isolation_1(self):
        self.assertEqual(self.session.scalar(func.count(TestModel.id)), 0)
        self.session.add(TestModel(name="test", value=1))
        self.session.commit()
        self.assertEqual(self.session.scalar(func.count(TestModel.id)), 1)

    def test_isolation_2(self):
        self.assertEqual(self.session.scalar(func.count(TestModel.id)), 0)
        self.session.add(TestModel(name="test", value=1))
        self.session.commit()
        self.assertEqual(self.session.scalar(func.count(TestModel.id)), 1)
