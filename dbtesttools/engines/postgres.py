# Copyright (c) 2021 Cisco Systems, Inc. and its affiliates
# All rights reserved.

import random
import socket
import sys
from contextlib import closing

import docker
import psycopg2
import sqlalchemy as sa
from retry import retry

from dbtesttools.baseengine import EngineFixture

DEFAULT_INIT_SQL = """
CREATE DATABASE testing WITH
    ENCODING = 'UTF8'
    LC_COLLATE = 'en_US.utf8'
    LC_CTYPE = 'en_US.utf8';
CREATE USER testing WITH ENCRYPTED PASSWORD 'testing';
GRANT ALL PRIVILEGES ON DATABASE testing TO testing;
"""


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
