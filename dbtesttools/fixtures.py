# Copyright (c) 2021 Cisco Systems, Inc. and its affiliates
# All rights reserved.

import abc
import importlib
import itertools
import os
import random
import socket
import sys
from contextlib import closing

import docker
import fixtures
import psycopg2
import sqlalchemy as sa
import testresources
from retry import retry

models_loaded = False


DEFAULT_INIT_SQL = """
CREATE DATABASE testing WITH
    ENCODING = 'UTF8'
    LC_COLLATE = 'en_US.utf8'
    LC_CTYPE = 'en_US.utf8';
CREATE USER testing WITH ENCRYPTED PASSWORD 'testing';
GRANT ALL PRIVILEGES ON DATABASE testing TO testing;
"""


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


class PostgresContainerFixture(EngineFixture):
    """A Postgres Docker-based database fixture.

    :param image: Name of the postgres docker image to pull and use.
    :param name: base name prefix for all started container instances.
    :param init_sql: Optional string of SQL to run in the newly-created
        database. Defaults to setting up a database/user called 'testing'
        with UTF8 encoding and collation.
    :param pg_data: PGDATA to pass to the container, defaults to /tmp/pgdata
    :param isolation: Optional default isolation level to use in the database.
    :param future: Passed directly to SQLAlchemy's `create_engine`.
        If true, activates the v2 API. Defaults to False.
    """

    def __init__(
        self,
        # Using the larger non-alpine image causes sort-order errors
        # because of locale collation differences.
        # image='postgres:11.4',
        image='postgres:11.11-alpine',
        name='testdb',
        init_sql=None,
        pg_data='/tmp/pgdata',  # nosec
        isolation=None,
        future=False,
    ):
        super().__init__()
        self.image = image
        self.name = name
        if init_sql is None:
            init_sql = DEFAULT_INIT_SQL
        self.init_sql = init_sql
        self.pg_data = pg_data
        self.isolation = isolation
        self.future = future

    def connect(self):
        """Return a connection object from the engine."""
        return self.engine.connect()

    @property
    def has_savepoint(self):
        # PG can roll back transactions, so is never dirty.
        return True

    # Internal methods below here.

    def setUp(self):
        """Do all the work to bring up a working Postgres fixture."""
        super().setUp()
        self.client = docker.from_env()
        self.pull_image()
        self.find_free_port()
        self.start_container()
        self.wait_for_pg_start()
        self.set_up_test_database()
        self.engine = sa.create_engine(
            'postgresql://testing:testing@127.0.0.1:{port}/testing'.format(
                port=self.local_port
            ),
            isolation_level=self.isolation,
            future=self.future,
        )
        self.addCleanup(self.container.kill)

    def pull_image(self):
        try:
            self.client.images.get(self.image)
        except docker.errors.ImageNotFound:
            print("Pulling Postgres image ...", file=sys.stderr)
            self.client.images.pull(self.image)

    def start_container(self):
        env = dict(POSTGRES_PASSWORD='postgres', PGDATA=self.pg_data)  # nosec
        ports = {'5432': self.local_port}
        print("Starting Postgres container ...", file=sys.stderr)
        # Randomize the name as threaded tests will create multiple containers.
        name = self.name + '-{}'.format(random.randint(1, 1000))  # nosec
        self.container = self.client.containers.run(
            self.image,
            detach=True,
            auto_remove=True,
            environment=env,
            name=name,
            network_mode='bridge',
            ports=ports,
            remove=True,
        )

    def find_free_port(self):
        """Find a free port on which to run Postgres locally."""
        # This initially binds to port 0, which makes the kernel pick a
        # real free port. We close the socket after determnining which port
        # that was.
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            s.bind(('localhost', 0))
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.local_port = s.getsockname()[1]
            print("Using port {}".format(self.local_port), file=sys.stderr)

    def set_up_test_database(self):
        c = psycopg2.connect(
            "dbname='postgres' "
            "user='postgres' host='127.0.0.1' port='{port}' "
            "password='postgres' connect_timeout=1".format(
                port=self.local_port
            )
        )
        c.autocommit = True
        cur = c.cursor()
        for stmt in self.init_sql.split(';'):
            if stmt.strip():
                cur.execute(stmt)
        cur.close()
        c.close()

    @retry(psycopg2.OperationalError, tries=30, delay=1)
    def wait_for_pg_start(self):
        c = psycopg2.connect(
            "user='postgres' host='127.0.0.1' port='{port}'"
            "password='postgres' connect_timeout=1".format(
                port=self.local_port
            )
        )
        c.close()
        print("Postgres is up", file=sys.stderr)


class DatabaseResource(testresources.TestResourceManager):
    """Test resource that sets up and tears down a database.

    This resource is intended to be used as a testresource, such that it is
    created only once per process. A database `engine` is created,
    which pools all connections.

    The resource also monkey patches the global Session registry so that
    it uses one configured to scope sessions to an identifier that is
    incremented by the SessionFixture. This enables a DB session to exist
    across only one test at a time, ensuring test isolation. Note that this
    is NOT safe to use for tests that are parallelised in threads. Use a
    test runner that starts separate processes.

    :param ModelBase: The SQLAlchemy ModelBase that your database objects are
        using. It is required so the models can be bound to the temporary test
        database engine for table creation.

    :param models_module: The python module name that contains your SQLAlchemy
        models. The models will be imported at the right moment when
        bringing up the DB.
        e.g. 'myproject.schema.models'

    :param patch_query_property: If True, override the `query` property on
        ModelBase so that it uses the Session registry's `query_property`.
        If your code does things like `FooModel.query.filter_by()` then you
        need this. `Query` is deprecated as of SQLAlchemy 1.4 which introduces
        the new v2 API.
        DEFAULT: False

    :param sessionmaker_class: Any custom class for SQLAlchemy's sessionmaker.
        Usually provided if you have a class with a custom get_bind, otherwise
        uses SQLAchemy's default.

    """

    def __init__(
        self,
        ModelBase,
        models_module,  # NOSONAR
        patch_query_property=False,
        engine_fixture_name='SqliteMemoryFixture',
        sessionmaker_class=None,
        engine_fixture_kwargs=None,
        future=False,
    ):
        super().__init__()
        self.models_module = models_module
        self.ModelBase = ModelBase
        self.patch_query_property = patch_query_property
        self.engine_fixture_name = engine_fixture_name
        self.sessionmaker_class = sessionmaker_class
        self.engine_fixture_kwargs = engine_fixture_kwargs or {}
        self.future = future
        self.engine_fixture_kwargs['future'] = self.future

    def make(self, dep_resources):
        print("Creating new database resource...", file=sys.stderr)
        self.initialize_engine()
        return self

    def _reset(self, resource, dependency_resources):
        # Override the base class to deliberately no-op. No resets are
        # necessary.
        return self

    @property
    def has_savepoint(self):
        return self.db.has_savepoint

    def clean(self, resource):
        print("Cleaning up database resource...", file=sys.stderr)
        self.drop_tables(self.engine)
        self.db.cleanUp()

    def pick_engine_fixture(self):
        env_name = os.environ.get('TEST_ENGINE_FIXTURE', None)
        module = sys.modules[globals()['__name__']]
        if env_name is not None:
            self.engine_fixture_name = env_name
        return getattr(module, self.engine_fixture_name)(
            **self.engine_fixture_kwargs
        )

    def initialize_engine(self):
        self.db = self.pick_engine_fixture()

        self.db.setUp()
        self._session_id_iterator = itertools.count(1)
        self._session_id = next(self._session_id_iterator)
        if self.sessionmaker_class is not None:
            session_factory = sa.orm.sessionmaker(
                class_=self.sessionmaker_class
            )
        else:
            session_factory = sa.orm.sessionmaker()

        # The session maker is declared in this resource so that it
        # can be scoped on a counter that persists across the whole
        # test run.
        self.Session = sa.orm.scoped_session(
            session_factory, scopefunc=self.session_id
        )

        # If still using the v1 Query API, optionally patch in a query
        # property on the ModelBase.
        if self.patch_query_property:
            self.ModelBase.query = self.Session.query_property()

        self.load_models()
        self.create_tables(self.db.engine)

    def _load_models(self):
        importlib.import_module(self.models_module)

    def load_models(self):
        """Load DB models just once, across all threads."""
        global models_loaded
        if models_loaded is False:
            models_loaded = True
            self._load_models()

    @property
    def engine(self):
        """Return the Engine in use."""
        return self.db.engine

    def next_session_id(self):
        """Call from the Session Fixture when a new session's required."""
        self._session_id = next(self._session_id_iterator)
        return self._session_id

    def session_id(self):
        return self._session_id

    def connect(self):
        """Get a connection object from the engine in the DB fixture."""
        return self.db.connect()

    def create_tables(self, engine):
        metadata = self.ModelBase.metadata
        metadata.create_all(bind=engine)

    def drop_tables(self, engine):
        metadata = self.ModelBase.metadata
        metadata.drop_all(bind=engine)

    def rollback_transaction(self, txn):
        """Roll back an in-progress transaction.

        If the database supports savepoints, this is trivial.
        If it does not, the database is blown away and recreated.
        """
        if not self.db.has_savepoint:
            # The DB Fixture can't do rollbacks, blow away the whole fixture
            # and recreate.
            if self.db._cleanups:
                # Work around bug in Fixtures by checking for any cleanups
                # first.
                self.db.cleanUp()
            self.initialize_engine()
        else:
            # The DB fixture can do rollbacks.
            txn.rollback()


class SessionFixture(fixtures.Fixture):
    """Test fixture that sets up a database session.

    The session is completely rolled back at the end of the fixture's lifespan
    so that the database remains clean.

    See https://docs.sqlalchemy.org/en/latest/orm/contextual.html for details
    on how scoped sessions work, with particular attention to custom
    scope functions.

    :param database_fixture: An initialised DatabaseResource object
    :param future: Future (v2) mode, passed directly to the engine and session
    :param debug: If true, send all DB statements emitted to the log.
    """

    def __init__(self, database_fixture, future=False, debug=False):
        super().__init__()
        self.database = database_fixture
        self.future = future
        if debug:
            self.database.engine.echo = True
            from logging import Formatter, getLogger

            log = getLogger("sqlalchemy.engine.Engine")
            log.handlers[0].setFormatter(
                Formatter("[%(levelname)s] %(message)s")
            )

    def setUp(self):
        super().setUp()
        self.connection = self.database.connect()
        self.txn = self.connection.begin()
        self.configure_session()
        self.session = self.Session()
        # Even if the DB won't do savepoints, begin a nested transaction
        # anyway. This makes SQLite tests pass.
        self.set_up_savepoint()

        self.addCleanup(self.clean_session)

    def configure_session(self):
        """Set up a pre-configured Session factory object."""
        if self.future:
            # v2 API binds via the connection
            self.database.Session.configure(
                future=self.future, bind=self.connection
            )
        # v1 API binds via the engine
        else:
            self.database.Session.configure(
                future=self.future,
                bind=self.database.engine,
            )

    @property
    def Session(self):
        """Get a session factory."""
        return self.database.Session

    def set_up_savepoint(self):
        # begin_nested() creates a SAVEPOINT, so that any transactions
        # committed in tests can still be rolled back. We create a
        # two-tier nesting - the outer txn is the master
        # isolation, and the inner savepoint is automatically recreated
        # if any test commits or rolls back. This ensures that the outer
        # txn is never touched by tests (or code called by tests).
        if self.future:
            # V2 API uses connections for nesting
            self.start_savepoint()
        else:
            # V1 API uses sessions for nesting
            self.session.begin_nested()

        @sa.event.listens_for(self.session, "after_transaction_end")
        def restart_savepoint(session, transaction):
            if self.future:
                if not self.savepoint.is_active:
                    self.start_savepoint()
            elif transaction.nested and not transaction._parent.nested:
                session.expire_all()
                session.begin_nested()

    def start_savepoint(self):
        # In SQLAlchemy v2 API, commiting a session with an active
        # savepoint commits the outer transaction. In v1 it just
        # committed the savepoint. The outer transaction on the connection
        # is now outside of the session itself so any session commits
        # will just result in a savepoint release.
        self.savepoint = self.connection.begin_nested()

    def clean_session(self):
        try:
            self.session.close()
        except sa.exc.OperationalError:
            # I think there's a bug in SQLA; it tries to rollback a
            # non-existent savepoint if any code under test has also done a
            # rollback.  We can safely ignore as we're about to roll back
            # the outer transaction anyway.
            pass
        self.database.rollback_transaction(self.txn)
        # Return connection to Engine's pool.
        self.connection.close()
        self.database.next_session_id()
