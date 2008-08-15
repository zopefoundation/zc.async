.. _configuration-with-zope-3:

=========================
Configuration with Zope 3
=========================

Our last main section can be the shortest yet, both because we've already
introduced all of the main concepts, and because we will be leveraging
conveniences to automate much of the configuration shown in the section
discussing configuration without Zope 3.

Client Set Up
=============

If you want to set up a client alone, without a dispatcher, include the egg in
your setup.py, include the configure.zcml in your applications zcml, make sure
you share the database in which the queues will be held, and make sure that
either the zope.app.keyreference.persistent.connectionOfPersistent adapter is
registered, or zc.twist.connection.

That should be it.

Client/Server Set Up
====================

For a client/server combination, use zcml that is something like the
basic_dispatcher_policy.zcml, make sure you have access to the database with
the queues, configure logging and monitoring as desired, configure the
``ZC_ASYNC_UUID`` environmental variable in zdaemon.conf if you are in
production, and start up! Getting started is really pretty easy. You can even
start a dispatcher-only version by not starting any servers in zcml.

In comparison to the non-Zope 3 usage, an important difference in your setup.py
is that, if you want the full set up described below, including zc.z3monitor,
you'll need to specify "zc.async [z3]" as the desired package in your
``install_requires``, as opposed to just "zc.async" [#extras_require]_.

We'll look at this by making a zope.conf-alike and a site.zcml-alike.  We'll
need a place to put some files, so we'll use a temporary directory.  This, and
the comments in the files that we set up, are the primary differences between
our examples and a real set up.

We'll do this in two versions.  The first version uses a single database, as
you might do to get started quickly, or for a small site.  The second version
has one database for the main application, and one database for the async data,
as will be more appropriate for typical production usage.

.. toctree::
   :maxdepth: 2
   
   README_3a
   README_3b

.. rubric:: Footnotes

.. [#extras_require] The "[z3]" is an "extra", defined in zc.async's setup.py
    in ``extras_require``. It pulls along zc.z3monitor and simplejson in
    addition to the packages described in the
    :ref:`configuration-without-zope-3` section. Unfortunately, zc.z3monitor
    depends on zope.app.appsetup, which as of this writing ends up depending
    indirectly on many, many packages, some as far flung as zope.app.rotterdam.
