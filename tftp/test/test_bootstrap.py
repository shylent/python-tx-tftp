'''
@author: shylent
'''
from tftp.bootstrap import (LocalOriginWriteSession, LocalOriginReadSession, 
    RemoteOriginReadSession, RemoteOriginWriteSession)
from tftp.datagram import (ACKDatagram, TFTPDatagramFactory, split_opcode, 
    ERR_TID_UNKNOWN, DATADatagram)
from tftp.test.test_sessions import DelayedWriter, FakeTransport, DelayedReader
from twisted.internet import reactor
from twisted.internet.defer import inlineCallbacks
from twisted.internet.task import Clock
from twisted.python.filepath import FilePath
from twisted.trial import unittest
import shutil
import tempfile


class MockHandshakeWatchdog(object):

    def __init__(self, when, f, args=None, kwargs=None, _clock=None):
        self._clock = _clock
        self.when = when
        self.f = f
        self.args = args or []
        self.kwargs = kwargs or {}
        if _clock is None:
            self._clock = reactor
        else:
            self._clock = _clock

    def start(self):
        self.wd = self._clock.callLater(self.when, self.f, *self.args, **self.kwargs)

    def cancel(self):
        if self.wd.active():
            self.wd.cancel()

    def active(self):
        return self.wd.active()


class BootstrapLocalOriginWrite(unittest.TestCase):

    port = 65466

    def setUp(self):
        self.clock = Clock()
        self.tmp_dir_path = tempfile.mkdtemp()
        self.target = FilePath(self.tmp_dir_path).child('foo')
        self.writer = DelayedWriter(self.target, _clock=self.clock, delay=2)
        self.transport = FakeTransport(hostAddress=('127.0.0.1', self.port))
        self.ws = LocalOriginWriteSession(('127.0.0.1', 65465), self.writer, _clock=self.clock)
        self.wd = MockHandshakeWatchdog(4, self.ws.cancel, _clock=self.clock)
        self.ws.handshake_timeout_watchdog = self.wd
        self.ws.transport = self.transport

    @inlineCallbacks
    def test_invalid_tid(self):
        bad_tid_dgram = ACKDatagram(123)
        yield self.ws.datagramReceived(bad_tid_dgram.to_wire(), ('127.0.0.1', 1111))
        err_dgram = TFTPDatagramFactory(*split_opcode(self.transport.value()))
        self.assertEqual(err_dgram.errorcode, ERR_TID_UNKNOWN)
        self.addCleanup(self.ws.cancel)
    #test_invalid_tid.skip = 'Will go to another test case'

    def test_local_origin_write_session_handshake_timeout(self):
        self.ws.startProtocol()
        self.clock.advance(5)
        self.failIf(self.transport.value())
        self.failUnless(self.transport.disconnecting)

    def test_local_origin_write_session_handshake_success(self):
        self.ws.startProtocol()
        self.clock.advance(1)
        data_datagram = DATADatagram(1, 'foobar')
        d = self.ws.datagramReceived(data_datagram.to_wire(), ('127.0.0.1', 65465))
        def cb(ign):
            self.clock.advance(0.1)
            self.assertEqual(self.transport.value(), ACKDatagram(1).to_wire())
            self.failIf(self.transport.disconnecting)
            self.failIf(self.wd.active())
        self.clock.advance(2)
        d.addCallback(cb)
        self.addCleanup(self.ws.cancel)
        return d

    def tearDown(self):
        shutil.rmtree(self.tmp_dir_path)


class BootstrapLocalOriginRead(unittest.TestCase):
    test_data = """line1
line2
anotherline"""
    port = 65466

    def setUp(self):
        self.clock = Clock()
        self.tmp_dir_path = tempfile.mkdtemp()
        self.target = FilePath(self.tmp_dir_path).child('foo')
        with self.target.open('wb') as temp_fd:
            temp_fd.write(self.test_data)
        self.reader = DelayedReader(self.target, _clock=self.clock, delay=2)
        self.transport = FakeTransport(hostAddress=('127.0.0.1', self.port))
        self.rs = LocalOriginReadSession(('127.0.0.1', 65465), self.reader, _clock=self.clock)
        self.wd = MockHandshakeWatchdog(4, self.rs.cancel, _clock=self.clock)
        self.rs.handshake_timeout_watchdog = self.wd
        self.rs.transport = self.transport

    @inlineCallbacks
    def test_invalid_tid(self):
        self.rs.startProtocol()
        data_datagram = DATADatagram(1, 'foobar')
        yield self.rs.datagramReceived(data_datagram, ('127.0.0.1', 11111))
        err_dgram = TFTPDatagramFactory(*split_opcode(self.transport.value()))
        self.assertEqual(err_dgram.errorcode, ERR_TID_UNKNOWN)
        self.addCleanup(self.rs.cancel)

    def test_local_origin_read_session_handshake_timeout(self):
        self.rs.startProtocol()
        self.clock.advance(5)
        self.failIf(self.transport.value())
        self.failUnless(self.transport.disconnecting)

    def test_local_origin_read_session_handshake_success(self):
        self.rs.startProtocol()
        self.clock.advance(1)
        ack_datagram = ACKDatagram(0)
        d = self.rs.datagramReceived(ack_datagram.to_wire(), ('127.0.0.1', 65465))
        def cb(ign):
            self.clock.advance(0.1)
            self.failUnless(self.transport.value())
            self.failIf(self.transport.disconnecting)
            self.failIf(self.wd.active())
        self.addCleanup(self.rs.cancel)
        d.addCallback(cb)
        self.clock.advance(2)
        return d

    def tearDown(self):
        shutil.rmtree(self.tmp_dir_path)


class BootstrapRemoteOriginRead(unittest.TestCase):
    test_data = """line1
line2
anotherline"""
    port = 65466

    def setUp(self):
        self.clock = Clock()
        self.tmp_dir_path = tempfile.mkdtemp()
        self.target = FilePath(self.tmp_dir_path).child('foo')
        with self.target.open('wb') as temp_fd:
            temp_fd.write(self.test_data)
        self.reader = DelayedReader(self.target, _clock=self.clock, delay=2)
        self.transport = FakeTransport(hostAddress=('127.0.0.1', self.port))
        self.rs = RemoteOriginReadSession(('127.0.0.1', 65465), self.reader, _clock=self.clock)
        self.rs.transport = self.transport

    @inlineCallbacks
    def test_invalid_tid(self):
        data_datagram = DATADatagram(1, 'foobar')
        yield self.rs.datagramReceived(data_datagram, ('127.0.0.1', 11111))
        err_dgram = TFTPDatagramFactory(*split_opcode(self.transport.value()))
        self.assertEqual(err_dgram.errorcode, ERR_TID_UNKNOWN)
        self.addCleanup(self.rs.cancel)

    def test_remote_origin_read_bootstrap(self):
        # First datagram
        self.rs.session.block_size = 5
        d = self.rs.startProtocol()
        def cb(res):
            self.clock.advance(0.1) # because write is scheduled with callLater(0, ...)
            data_datagram_1 = DATADatagram(1, self.test_data[:5])

            self.assertEqual(self.transport.value(), data_datagram_1.to_wire())
            self.failIf(self.transport.disconnecting)

            # Normal exchange continues
            self.transport.clear()
            d = self.rs.datagramReceived(ACKDatagram(1).to_wire(), ('127.0.0.1', 65465))
            d.addCallback(cb_)
            self.clock.advance(3)
            return d
        def cb_(z):
            self.clock.advance(0.1) # same story here
            data_datagram_2 = DATADatagram(2, self.test_data[5:10])
            self.assertEqual(self.transport.value(), data_datagram_2.to_wire())
            self.failIf(self.transport.disconnecting)
            self.addCleanup(self.rs.cancel)

        d.addCallback(cb)
        self.clock.advance(3)
        return d

    def tearDown(self):
        shutil.rmtree(self.tmp_dir_path)


class BootstrapRemoteOriginWrite(unittest.TestCase):

    port = 65466

    def setUp(self):
        self.clock = Clock()
        self.tmp_dir_path = tempfile.mkdtemp()
        self.target = FilePath(self.tmp_dir_path).child('foo')
        self.writer = DelayedWriter(self.target, _clock=self.clock, delay=2)
        self.transport = FakeTransport(hostAddress=('127.0.0.1', self.port))
        self.ws = RemoteOriginWriteSession(('127.0.0.1', 65465), self.writer, _clock=self.clock)
        self.ws.transport = self.transport

    @inlineCallbacks
    def test_invalid_tid(self):
        bad_tid_dgram = ACKDatagram(123)
        yield self.ws.datagramReceived(bad_tid_dgram.to_wire(), ('127.0.0.1', 1111))
        err_dgram = TFTPDatagramFactory(*split_opcode(self.transport.value()))
        self.assertEqual(err_dgram.errorcode, ERR_TID_UNKNOWN)
        self.addCleanup(self.ws.cancel)

    def test_remote_origin_write_bootstrap(self):
        # Initial ACK
        self.ws.startProtocol()
        ack_datagram_0 = ACKDatagram(0)
        self.clock.advance(0.1)
        self.assertEqual(self.transport.value(), ack_datagram_0.to_wire())
        self.failIf(self.transport.disconnecting)

        # Normal exchange
        self.transport.clear()
        d = self.ws.datagramReceived(DATADatagram(1, 'foobar').to_wire(), ('127.0.0.1', 65465))
        def cb(res):
            self.clock.advance(0.1)
            ack_datagram_1 = ACKDatagram(1)
            self.assertEqual(self.transport.value(), ack_datagram_1.to_wire())
            self.assertEqual(self.target.open('r').read(), 'foobar')
            self.failIf(self.transport.disconnecting)
            self.addCleanup(self.ws.cancel)
        d.addCallback(cb)
        self.clock.advance(3)
        return d

    def tearDown(self):
        shutil.rmtree(self.tmp_dir_path)
