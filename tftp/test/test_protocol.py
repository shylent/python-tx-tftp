'''
@author: shylent
'''

from tftp.datagram import (WRQDatagram, TFTPDatagramFactory, split_opcode,
    ERR_ILLEGAL_OP, RRQDatagram, ERR_ACCESS_VIOLATION, ERR_FILE_EXISTS,
    ERR_FILE_NOT_FOUND, ERR_NOT_DEFINED)
from tftp.errors import (Unsupported, AccessViolation, FileExists, FileNotFound,
    BackendError)
from tftp.protocol import TFTP
from twisted.internet.task import Clock
from twisted.test.proto_helpers import StringTransport
from twisted.trial import unittest


class DummyBackend(object):
    pass

def BackendFactory(exc_val=None):
    if exc_val is not None:
        class FailingBackend(object):
            def get_reader(self, filename):
                raise exc_val
            def get_writer(self, filename):
                raise exc_val
        return FailingBackend()
    else:
        return DummyBackend()


class FakeTransport(StringTransport):
    stopListening = StringTransport.loseConnection

    def write(self, bytes, addr=None):
        StringTransport.write(self, bytes)

    def connect(self, host, port):
        self._connectedAddr = (host, port)


class DispatchErrors(unittest.TestCase):
    port = 11111

    def setUp(self):
        self.clock = Clock()
        self.transport = FakeTransport(hostAddress=('127.0.0.1', self.port))

    def test_malformed_datagram(self):
        tftp = TFTP(BackendFactory(), _clock=self.clock)
        tftp.datagramReceived('foobar', ('127.0.0.1', 1111))
        self.failIf(self.transport.disconnecting)
        self.failIf(self.transport.value())
    test_malformed_datagram.skip = 'Not done yet'

    def test_bad_mode(self):
        tftp = TFTP(DummyBackend(), _clock=self.clock)
        tftp.transport = self.transport
        wrq_datagram = WRQDatagram('foobar', 'badmode', {})
        tftp.datagramReceived(wrq_datagram.to_wire(), ('127.0.0.1', 1111))
        error_datagram = TFTPDatagramFactory(*split_opcode(self.transport.value()))
        self.assertEqual(error_datagram.errorcode, ERR_ILLEGAL_OP)

    def test_unsupported(self):
        tftp = TFTP(BackendFactory(Unsupported("I don't support you")), _clock=self.clock)
        tftp.transport = self.transport
        wrq_datagram = WRQDatagram('foobar', 'netascii', {})
        tftp.datagramReceived(wrq_datagram.to_wire(), ('127.0.0.1', 1111))
        error_datagram = TFTPDatagramFactory(*split_opcode(self.transport.value()))
        self.assertEqual(error_datagram.errorcode, ERR_ILLEGAL_OP)

        self.transport.clear()
        rrq_datagram = RRQDatagram('foobar', 'octet', {})
        tftp.datagramReceived(rrq_datagram.to_wire(), ('127.0.0.1', 1111))
        error_datagram = TFTPDatagramFactory(*split_opcode(self.transport.value()))
        self.assertEqual(error_datagram.errorcode, ERR_ILLEGAL_OP)

    def test_access_violation(self):
        tftp = TFTP(BackendFactory(AccessViolation("No!")), _clock=self.clock)
        tftp.transport = self.transport
        wrq_datagram = WRQDatagram('foobar', 'netascii', {})
        tftp.datagramReceived(wrq_datagram.to_wire(), ('127.0.0.1', 1111))
        error_datagram = TFTPDatagramFactory(*split_opcode(self.transport.value()))
        self.assertEqual(error_datagram.errorcode, ERR_ACCESS_VIOLATION)

        self.transport.clear()
        rrq_datagram = RRQDatagram('foobar', 'octet', {})
        tftp.datagramReceived(rrq_datagram.to_wire(), ('127.0.0.1', 1111))
        error_datagram = TFTPDatagramFactory(*split_opcode(self.transport.value()))
        self.assertEqual(error_datagram.errorcode, ERR_ACCESS_VIOLATION)

    def test_file_exists(self):
        tftp = TFTP(BackendFactory(FileExists("Already have one")), _clock=self.clock)
        tftp.transport = self.transport
        wrq_datagram = WRQDatagram('foobar', 'netascii', {})
        tftp.datagramReceived(wrq_datagram.to_wire(), ('127.0.0.1', 1111))
        error_datagram = TFTPDatagramFactory(*split_opcode(self.transport.value()))
        self.assertEqual(error_datagram.errorcode, ERR_FILE_EXISTS)

    def test_file_not_found(self):
        tftp = TFTP(BackendFactory(FileNotFound("Not found")), _clock=self.clock)
        tftp.transport = self.transport
        rrq_datagram = RRQDatagram('foobar', 'netascii', {})
        tftp.datagramReceived(rrq_datagram.to_wire(), ('127.0.0.1', 1111))
        error_datagram = TFTPDatagramFactory(*split_opcode(self.transport.value()))
        self.assertEqual(error_datagram.errorcode, ERR_FILE_NOT_FOUND)

    def test_generic_backend_error(self):
        tftp = TFTP(BackendFactory(BackendError("A backend that couldn't")), _clock=self.clock)
        tftp.transport = self.transport
        rrq_datagram = RRQDatagram('foobar', 'netascii', {})
        tftp.datagramReceived(rrq_datagram.to_wire(), ('127.0.0.1', 1111))
        error_datagram = TFTPDatagramFactory(*split_opcode(self.transport.value()))
        self.assertEqual(error_datagram.errorcode, ERR_NOT_DEFINED)

        self.transport.clear()
        rrq_datagram = RRQDatagram('foobar', 'octet', {})
        tftp.datagramReceived(rrq_datagram.to_wire(), ('127.0.0.1', 1111))
        error_datagram = TFTPDatagramFactory(*split_opcode(self.transport.value()))
        self.assertEqual(error_datagram.errorcode, ERR_NOT_DEFINED)
