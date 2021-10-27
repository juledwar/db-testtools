# Copyright (c) 2021 Cisco Systems, Inc. and its affiliates
# All rights reserved.

import abc

import fixtures
import sqlalchemy as sa


class EngineFixture(fixtures.Fixture, metaclass=abc.ABCMeta):
    """Base class for engine fixtures.

    Fixtures are responsible for starting a complete database server,
    and to start/rollback an 'outer' transaction. Outer transactions
    are required to keep an effective save point so that any part of the
    test suite may issue commit and rollback requests.
    """

    @abc.abstractmethod
    def connect(self) -> sa.engine.base.Connection:
        """Return a new connection object from the Engine."""
        pass

    @property
    @abc.abstractmethod
    def has_savepoint(self) -> bool:
        """Define whether the engine can do savepoints or not.

        If an engine fixture cannot do savepoints, it must be torn down
        and re-made between tests. If it can, it tells the
        DatabaseResource that it supports mid-txn rollbacks via the
        savepoint.
        """
        pass
