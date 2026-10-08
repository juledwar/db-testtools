# Copyright (c) 2021 Cisco Systems, Inc. and its affiliates
# All rights reserved.

import abc
import warnings

import fixtures
import sqlalchemy as sa


def warn_future_deprecated(future, stacklevel=3):
    """Warn if the obsolete `future` argument was passed.

    SQLAlchemy 2 is always in "future" (v2) mode, so the argument no longer
    has any effect.
    """
    if future is not None:
        warnings.warn(
            "The 'future' argument is deprecated and ignored; "
            "db-testtools now requires SQLAlchemy 2, which always uses "
            "the v2 API.",
            DeprecationWarning,
            stacklevel=stacklevel,
        )


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
