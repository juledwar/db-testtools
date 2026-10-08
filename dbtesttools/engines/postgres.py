# Copyright (c) 2021-2026 Cisco Systems, Inc. and its affiliates
# All rights reserved.

import importlib
import os
import socket
import sys
from collections import namedtuple
from contextlib import closing
from itertools import count

import docker
import sqlalchemy as sa
from retry.api import retry_call

from dbtesttools.baseengine import EngineFixture, warn_future_deprecated

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

DRIVER_ENV_VAR = "DBTESTTOOLS_PG_DRIVER"

PgDriver = namedtuple("PgDriver", ["name", "module", "url_scheme"])

# Canonical driver name -> (DB-API module name, SQLAlchemy URL scheme).
_DRIVERS = {
    "psycopg2": ("psycopg2", "postgresql+psycopg2"),
    "psycopg": ("psycopg", "postgresql+psycopg"),
}
_DRIVER_ALIASES = {"psycopg3": "psycopg"}
# Auto-detection order when no driver is explicitly requested.
_AUTODETECT_ORDER = ("psycopg2", "psycopg")
_INSTALL_HINTS = {
    "psycopg2": "pip install psycopg2-binary",
    "psycopg": "pip install db-testtools[psycopg3]",
}


def _load_driver(name):
    module_name, url_scheme = _DRIVERS[name]
    module = importlib.import_module(module_name)
    return PgDriver(name, module, url_scheme)


def resolve_driver(name=None):
    """Find and import the Postgres DB-API driver to use.

    :param name: Requested driver name: 'psycopg2', 'psycopg' or
        'psycopg3' (an alias for 'psycopg'). If None, the
        DBTESTTOOLS_PG_DRIVER environment variable is consulted, and if
        that is also unset, the first importable driver is used,
        preferring psycopg2.
    :return: A `PgDriver` namedtuple of (name, module, url_scheme).
    :raises ValueError: If the driver name is not recognised.
    :raises ImportError: If the requested driver is not installed, or no
        driver at all can be found when auto-detecting.
    """
    if name is None:
        name = os.getenv(DRIVER_ENV_VAR) or None
    if name is not None:
        key = name.strip().lower()
        key = _DRIVER_ALIASES.get(key, key)
        if key not in _DRIVERS:
            raise ValueError(
                "Unknown Postgres driver {!r}; expected one of: {}".format(
                    name,
                    ", ".join(sorted(set(_DRIVERS) | set(_DRIVER_ALIASES))),
                )
            )
        try:
            return _load_driver(key)
        except ImportError as e:
            raise ImportError(
                "Postgres driver {!r} could not be imported ({}). "
                "Is it installed? Try: {}".format(name, e, _INSTALL_HINTS[key])
            ) from e

    errors = []
    for key in _AUTODETECT_ORDER:
        try:
            return _load_driver(key)
        except ImportError as e:
            errors.append("{}: {}".format(key, e))
    raise ImportError(
        "No usable Postgres driver found ({}). Install psycopg2-binary, "
        "or psycopg (v3) with: pip install db-testtools[psycopg3]".format(
            "; ".join(errors)
        )
    )


class PostgresContainerFixture(EngineFixture):
    """A Postgres Docker-based database fixture.

    :param image: Name of the postgres docker image to pull and use.
    :param name: base name prefix for all started container instances.
    :param init_sql: Optional string of SQL to run in the newly-created
        database. Defaults to setting up a database/user called 'testing'
        with UTF8 encoding and collation.
    :param pg_data: PGDATA to pass to the container, defaults to /tmp/pgdata
    :param isolation: Optional default isolation level to use in the database.
    :param future: Deprecated and ignored; SQLAlchemy 2 always uses the
        v2 API.
    :param ip_address: The address on which to contact the PG server after it
        comes up. This defaults to 127.0.0.1, which works if you are
        running your fixture via Docker on the same host, however if
        you're running inside a container already, the Postgres
        container that is brought up will have the IP address of the
        container's host. The DBTESTTOOLS_PG_IP_ADDR environment
        variable can also be used to override (this arg takes precedence
        though).
    :param driver: The DB-API driver to use, either 'psycopg2' or
        'psycopg' (psycopg v3, 'psycopg3' is also accepted). If not
        supplied, the DBTESTTOOLS_PG_DRIVER environment variable is used,
        otherwise the driver is auto-detected, preferring psycopg2 if it
        is installed.
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
        future=None,
        ip_address=None,
        driver=None,
    ):
        super().__init__()
        self.image = image
        self.name = name
        if init_sql is None:
            init_sql = DEFAULT_INIT_SQL
        self.init_sql = init_sql
        self.pg_data = pg_data
        self.isolation = isolation
        warn_future_deprecated(future)
        self.ip_address = ip_address or os.getenv(
            "DBTESTTOOLS_PG_IP_ADDR", "127.0.0.1"
        )
        self._driver = resolve_driver(driver)

    @property
    def driver(self):
        """The name of the DB-API driver in use ('psycopg2' or 'psycopg')."""
        return self._driver.name

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
        self.addCleanup(self.container.kill)
        # Because this overrides setUp() rather than _setUp(), fixtures will
        # not run cleanups if we fail, so do it here to avoid leaking the
        # container. Errors from cleanups are dropped so that the original
        # exception propagates.
        try:
            self.wait_for_pg_start()
            self.set_up_test_database()
            self.engine = self.create_engine()
        except BaseException:
            self.cleanUp(raise_first=False)
            raise

    def create_engine(self):
        """Create the SQLAlchemy engine for the test database."""
        return sa.create_engine(
            "{scheme}://testing:testing@{ip}:{port}/testing".format(
                scheme=self._driver.url_scheme,
                ip=self.ip_address,
                port=self.local_port,
            ),
            isolation_level=self.isolation,
        )

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
        c = self._driver.module.connect(
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

    def wait_for_pg_start(self):
        retry_call(
            self._try_pg_connect,
            exceptions=self._driver.module.OperationalError,
            tries=60,
            delay=1,
        )
        print("Postgres is up", file=sys.stderr)

    def _try_pg_connect(self):
        c = self._driver.module.connect(
            "user='postgres' host='{ip}' port='{port}' "
            "password='postgres' connect_timeout=1".format(
                ip=self.ip_address, port=self.local_port
            )
        )
        c.close()
