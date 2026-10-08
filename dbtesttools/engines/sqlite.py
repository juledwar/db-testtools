# Copyright (c) 2021 Cisco Systems, Inc. and its affiliates
# All rights reserved.

import sqlalchemy as sa

from dbtesttools.baseengine import EngineFixture, warn_future_deprecated


class SqliteMemoryFixture(EngineFixture):
    """A Sqlite memory-based DB fixture.

    :param future: Deprecated and ignored; SQLAlchemy 2 always uses the
        v2 API.

    Throw all other args/kwargs on the floor.
    (For compatibility with PyCharm's built-in test runner)
    """

    def __init__(self, *args, future=None, **kwargs):
        warn_future_deprecated(future)
        super().__init__()

    def setUp(self):
        super().setUp()
        self.engine = sa.create_engine('sqlite:///:memory:')
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
