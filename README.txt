``zc.async``
============

What is it?
-----------

The ``zc.async`` package provides **a Python tool that schedules work across
multiple processes and machines.**

For instance...

- *Web apps*: maybe your web application lets users request the creation of a
  large PDF, or some other expensive task.

- *Postponed work*: maybe you have a job that needs to be done at a certain time,
  not right now.

- *Parallel processing*: maybe you have a long-running problem that can be made
  to complete faster by splitting it up into discrete parts, each performed in
  parallel, across multiple machines.

- *Serial processing*: maybe you want to decompose and serialize a job.

High-level features include the following:

- easy to use;

- flexible configuration, changeable dynamically in production;

- reliable;

- supports high availability;

- good debugging tools;

- well-tested; and

- friendly to testing.

While developed as part of the Zope project, zc.async can be used stand-alone.

How does it work?
-----------------

The system uses the Zope Object Database (ZODB), a transactional, pickle-based
Python object database, for communication and coordination among participating
processes.

zc.async participants can each run in their own process, or share a process
(run in threads) with other code.

The Twisted framework supplies some code (failures and reactor implementations,
primarily) and some concepts to the package.