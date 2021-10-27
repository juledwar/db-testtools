# Copyright (c) 2021 Cisco Systems, Inc. and its affiliates
# All rights reserved.

import sqlalchemy as sa

from dbtesttools.baseengine import EngineFixture


class SqliteMemoryFixture(EngineFixture):
    """A Sqlite memory-based DB fixture.

    :param future: The future flag passed directly to SQLAlchemy's
        `create_engine`.

    Throw all other args/kwargs on the floor.
    (For compatibility with PyCharm's built-in test runner)
    """

    def __init__(self, *args, future=False, **kwargs):
        self.future = future
        super().__init__()

    def setUp(self):
        super().setUp()
        self.engine = sa.create_engine(
            'sqlite:///:memory:', future=self.future
        )
        self.connection = self.connect()
        self.connection.execute(sa.text('PRAGMA foreign_keys = ON'))
        self.addCleanup(self.connection.close)

    def connect(self):
        """Return a connection object from the engine."""
        return self.engine.connect()

    @property
    def has_savepoint(self):
        # This forces the database reasource to be rebuilt for every test.
        # Sqlite won't do nested transactions properly, so just throw the DB
        # away and start again.
        return False
