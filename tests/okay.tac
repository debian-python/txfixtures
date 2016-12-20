# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""
This TAC is used for the TacTestSetupTestCase.test_pidForNotRunningProcess
test case in test_tachandler.py.  It simply starts up correctly, listening on
a port that should typically be free.
"""

__metaclass__ = type

from twisted.application import service
from twisted.application import (
    internet,
    service,
    )
from twisted.internet import protocol

application = service.Application('Okay')
serviceCollection = service.IServiceCollection(application)
internet.TCPServer(9876, protocol.Factory()).setServiceParent(serviceCollection)

# vim: ft=python
