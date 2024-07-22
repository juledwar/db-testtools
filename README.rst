DB-TESTTOOLS
============

This package contains test fixtures and resources that bring up an
isolated database and SQLAlchemy test fixtures, so that your Python
unit tests will run without interfering with each other when you are
using the SQLAlchemy ORM.

The database is initialised once at the start of a test process run, as
is the session fixture. The session fixture ensures that any commits do
not permanently commit, and rolls back the database to a clean state
after each test completes.

Requirements
------------

Python 3.8 and beyond should work.

Quickstart
----------

Install with pip::

    pip install db-testtools

Example base test class:

.. code:: python

    class DBTestCase(testresources.ResourcedTestCase, testtools.TestCase):
        """Base class for all DB tests.

       Brings up a temporary database and gives each test its own session.
       """

       # These are resources that stay active for the entire
       # duration of all the tests being run.
       db_fixture = DatabaseResource(
           ModelBase,
           'myproject.models',
           future=True,
       )
       resources = [('database', db_fixture)]

       def setUp(self):
           super().setUp()

           self.session_fixture = SessionFixture(self.database, future=True)
           self.useFixture(self.session_fixture)
           # The session itself.
           self.session = self.session_fixture.session
           # The session factory.
           self.Session = self.session_fixture.Session


This base test class will start a SQLite-based database by default and
inject `self.session` as the SQLAlchemy session and `self.Session` as the
SQLAlchemy session factory.

If you need to use a different database, then you can either:
    - pass the `engine_fixture_name` parameter to `DatabaseResource`
    - set an environment variable TEST_ENGINE_FIXTURE

with the name of the engine fixture to use. Currently two are
available:

    - SqliteMemoryFixture
    - PostgresContainerFixture

Engine drivers
--------------

Currently the two drivers mentioned above are implemented. The SQLite
fixture implements a simple in-memory database which is completely
dropped and re-instated on every test.

The PostgresContainerFixture starts its own Postgres instance in a local
Docker container. Therefore you must have Docker installed before using
this fixture. The Postgres image used by default is 16.3-alpine, but this
fixture is known to work all the way back to v11.

If you are already running inside Docker you will need to start the
container with `--network-"host"` so that 127.0.0.1 routes to the started
PG containers. You will need to do up to two extra things:

 1. Bind mount /var/run/docker.sock to the container so docker clients
    can create sibling containers on the host.
 2. If you cannot use host networking, supply the IP address of the
    host's network bridge (usually docker0, etc), so that the fixture
    knows where to find the PG server. The IP address is either
    supplied via the constructor to `PostgresContainerFixture` or you
    can set the DBTESTTOOLS_PG_IP_ADDR environment variable.


This code has been in use daily on a large project at Cisco for a few years
now, and is very stable.


Copyright
---------

db-testtools is copyright (c) 2021-2024 Cisco Systems, Inc. and its affiliates
All rights reserved.
