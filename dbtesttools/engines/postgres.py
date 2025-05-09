# Copyright (c) 2021-2023 Cisco Systems, Inc. and its affiliates
# All rights reserved.

import os
import socket
import sys
from contextlib import closing
from itertools import count

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
GRANT ALL ON SCHEMA public TO testing;
ALTER DATABASE testing OWNER TO testing;
"""

NEXT_ID = count(1)


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
    :param ip_address: The address on which to contact the PG server after it
        comes up. This defaults to 127.0.0.1, which works if you are
        running your fixture via Docker on the same host, however if
        you're running inside a container already, the Postgres
        container that is brought up will have the IP address of the
        container's host. The DBTESTTOOLS_PG_IP_ADDR environment
        variable can also be used to override (this arg takes precedence
        though).
    """

    def __init__(
        self,
        # Using the larger non-alpine image causes sort-order errors
        # because of locale collation differences.
        # image='postgres:11.4',
        image="postgres:16.3-alpine",
        name="testdb",
        init_sql=None,
        pg_data="/tmp/pgdata",  # noqa: S108
        isolation=None,
        future=False,
        ip_address=None,
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
        self.ip_address = ip_address or os.getenv(
            "DBTESTTOOLS_PG_IP_ADDR", "127.0.0.1"
        )

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
        # Podman integration: optionally override Docker socket
        if os.getenv("DBTESTTOOLS_USE_PODMAN") == "1":
            if sys.platform == "darwin":
                # MacOS Podman socket
                podman_socket = (
                    f"unix://{os.getenv('HOME')}"
                    f"/.local/share/containers/podman/machine/podman.sock"
                )
            else:
                # Linux Podman socket
                podman_socket = (
                    f"unix:///run/user/{os.getuid()}/podman/podman.sock"
                )
            if os.path.exists(podman_socket.replace("unix://", "")):
                os.environ["DOCKER_HOST"] = podman_socket
            else:
                raise FileNotFoundError(
                    f"Podman socket not found at {podman_socket}"
                )

        self.client = docker.from_env()
        self.pull_image()
        self.find_free_port()
        self.start_container()
        self.wait_for_pg_start()
        self.set_up_test_database()
        self.engine = sa.create_engine(
            "postgresql://testing:testing@{ip}:{port}/testing".format(
                ip=self.ip_address, port=self.local_port
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
        env = dict(POSTGRES_PASSWORD="postgres", PGDATA=self.pg_data)  # noqa: S106
        ports = {"5432": self.local_port}
        print("Starting Postgres container ...", file=sys.stderr)
        # Uniq-ify the name as threaded tests will create multiple containers.
        name = "{}-{}.{}".format(self.name, os.getpid(), next(NEXT_ID))
        self.container = self.client.containers.run(
            self.image,
            detach=True,
            auto_remove=True,
            environment=env,
            name=name,
            network_mode="bridge",
            ports=ports,
            remove=True,
        )

    def find_free_port(self):
        """Find a free port on which to run Postgres locally."""
        # This initially binds to port 0, which makes the kernel pick a
        # real free port. We close the socket after determnining which port
        # that was.
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            s.bind(("localhost", 0))
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.local_port = s.getsockname()[1]
            print("Using port {}".format(self.local_port), file=sys.stderr)

    def set_up_test_database(self):
        c = psycopg2.connect(
            "dbname='postgres' "
            "user='postgres' host='{ip}' port='{port}' "
            "password='postgres' connect_timeout=1".format(
                ip=self.ip_address, port=self.local_port
            )
        )
        c.autocommit = True
        cur = c.cursor()
        for stmt in self.init_sql.split(";"):
            if stmt.strip():
                cur.execute(stmt)
        cur.close()
        c.close()

    @retry(psycopg2.OperationalError, tries=60, delay=1)
    def wait_for_pg_start(self):
        c = psycopg2.connect(
            "user='postgres' host='{ip}' port='{port}'"
            "password='postgres' connect_timeout=1".format(
                ip=self.ip_address, port=self.local_port
            )
        )
        c.close()
        print("Postgres is up", file=sys.stderr)
