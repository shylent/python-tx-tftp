'''
@author: shylent
'''
from tftp.backend import FilesystemWriter, FilesystemReader, IReader, IWriter
from tftp.datagram import (ACKDatagram, ERRORDatagram, ERR_TID_UNKNOWN,
    ERR_NOT_DEFINED, DATADatagram, TFTPDatagramFactory, split_opcode)
from tftp.session import (WriteSession, ReadSession, LocalOriginWriteSession,
    LocalOriginReadSession, RemoteOriginReadSession, RemoteOriginWriteSession)
from twisted.internet import reactor
from twisted.internet.defer import Deferred, inlineCallbacks
from twisted.internet.task import Clock
from twisted.python.filepath import FilePath
from twisted.test.proto_helpers import StringTransport
from twisted.trial import unittest
from zope import interface
import shutil
import tempfile


class DelayedReader(FilesystemReader):

    def __init__(self, *args, **kwargs):
        self.delay = kwargs.pop('delay')
        self._clock = kwargs.pop('_clock', reactor)
        FilesystemReader.__init__(self, *args, **kwargs)

    def read(self, size):
        data = FilesystemReader.read(self, size)
        d = Deferred()
        def c(ign):
            return data
        d.addCallback(c)
        self._clock.callLater(self.delay, d.callback, None)
        return d


class DelayedWriter(FilesystemWriter):

    def __init__(self, *args, **kwargs):
        self.delay = kwargs.pop('delay')
        self._clock = kwargs.pop('_clock', reactor)
        FilesystemWriter.__init__(self, *args, **kwargs)

    def write(self, data):
        d = Deferred()
        def c(ign):
            return FilesystemWriter.write(self, data)
        d.addCallback(c)
        self._clock.callLater(self.delay, d.callback, None)
        return d


class FailingReader(object):
    interface.implements(IReader)

    def read(self, size):
        raise IOError('A failure')

    def finish(self):
        pass


class FailingWriter(object):
    interface.implements(IWriter)

    def write(self, data):
        raise IOError("I fail")

    def cancel(self):
        pass

    def finish(self):
        pass


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


class FakeTransport(StringTransport):
    stopListening = StringTransport.loseConnection

    def connect(self, host, port):
        self._connectedAddr = (host, port)


class WriteSessions(unittest.TestCase):

    port = 65466

    def setUp(self):
        self.clock = Clock()
        self.tmp_dir_path = tempfile.mkdtemp()
        self.target = FilePath(self.tmp_dir_path).child('foo')
        self.writer = DelayedWriter(self.target, _clock=self.clock, delay=2)
        self.transport = FakeTransport(hostAddress=('127.0.0.1', self.port))
        self.ws = WriteSession(('127.0.0.1', 65465), self.writer, _clock=self.clock)
        self.ws.timeout = 5
        self.ws.transport = self.transport
        self.ws.startProtocol()

    @inlineCallbacks
    def test_invalid_tid(self):
        bad_tid_dgram = ACKDatagram(123)
        yield self.ws.datagramReceived(bad_tid_dgram.to_wire(), ('127.0.0.1', 1111))
        err_dgram = TFTPDatagramFactory(*split_opcode(self.transport.value()))
        self.assertEqual(err_dgram.errorcode, ERR_TID_UNKNOWN)
        self.addCleanup(self.ws.cancel)
    test_invalid_tid.skip = 'Will go to another test case'

    @inlineCallbacks
    def test_ERROR(self):
        err_dgram = ERRORDatagram.from_code(ERR_NOT_DEFINED, 'no reason')
        yield self.ws.datagramReceived(err_dgram, ('127.0.0.1', 65465))
        self.failIf(self.transport.value())
        self.failUnless(self.transport.disconnecting)

    @inlineCallbacks
    def test_DATA_stale_blocknum(self):
        self.ws.block_size = 6
        self.ws.blocknum = 2
        data_datagram = DATADatagram(1, 'foobar')
        yield self.ws.datagramReceived(data_datagram, ('127.0.0.1', 65465))
        self.writer.finish()
        self.failIf(self.target.open('r').read())
        self.failIf(self.transport.disconnecting)
        ack_dgram = TFTPDatagramFactory(*split_opcode(self.transport.value()))
        self.assertEqual(ack_dgram.blocknum, 1)
        self.addCleanup(self.ws.cancel)

    @inlineCallbacks
    def test_DATA_invalid_blocknum(self):
        self.ws.block_size = 6
        data_datagram = DATADatagram(3, 'foobar')
        yield self.ws.datagramReceived(data_datagram, ('127.0.0.1', 65465))
        self.writer.finish()
        self.failIf(self.target.open('r').read())
        self.failIf(self.transport.disconnecting)
        err_dgram = TFTPDatagramFactory(*split_opcode(self.transport.value()))
        self.assert_(isinstance(err_dgram, ERRORDatagram))
        self.addCleanup(self.ws.cancel)

    def test_DATA(self):
        self.ws.block_size = 6
        data_datagram = DATADatagram(1, 'foobar')
        d = self.ws.datagramReceived(data_datagram, ('127.0.0.1', 65465))
        def cb(ign):
            self.writer.finish()
            self.assertEqual(self.target.open('r').read(), 'foobar')
            self.failIf(self.transport.disconnecting)
            ack_dgram = TFTPDatagramFactory(*split_opcode(self.transport.value()))
            self.failUnless(isinstance(ack_dgram, ACKDatagram))
            self.failIf(self.ws.completed,
                        "Data length is equal to blocksize, no reason to stop")
        d.addCallback(cb)
        self.addCleanup(self.ws.cancel)
        self.clock.advance(3)
        return d

    def test_DATA_finished(self):
        self.ws.block_size = 6
        self.ws.timeout = 3

        # Send a terminating datagram
        data_datagram = DATADatagram(1, 'foo')
        d = self.ws.datagramReceived(data_datagram, ('127.0.0.1', 65465))
        def cb(res):
            self.assertEqual(self.target.open('r').read(), 'foo')
            ack_dgram = TFTPDatagramFactory(*split_opcode(self.transport.value()))
            self.failUnless(isinstance(ack_dgram, ACKDatagram))
            self.failUnless(self.ws.completed,
                        "Data length is less, than blocksize, time to stop")
            self.transport.clear()

            # Send another datagram after the transfer is considered complete
            data_datagram = DATADatagram(2, 'foobar')
            self.ws.datagramReceived(data_datagram, ('127.0.0.1', 65465))
            self.assertEqual(self.target.open('r').read(), 'foo')
            err_dgram = TFTPDatagramFactory(*split_opcode(self.transport.value()))
            self.failUnless(isinstance(err_dgram, ERRORDatagram))

            # Check for proper disconnection after grace timeout expires
            self.clock.advance(4)
            self.failUnless(self.transport.disconnecting,
                "We are done and the grace timeout is over, should disconnect")
        d.addCallback(cb)
        self.clock.advance(2)
        return d

    @inlineCallbacks
    def test_failed_write(self):
        self.ws.writer = FailingWriter()
        data_datagram = DATADatagram(1, 'foobar')
        yield self.ws.datagramReceived(data_datagram, ('127.0.0.1', 65465))
        self.flushLoggedErrors()
        self.clock.advance(0.1)
        err_datagram = TFTPDatagramFactory(*split_opcode(self.transport.value()))
        self.failUnless(isinstance(err_datagram, ERRORDatagram))
        self.failUnless(self.transport.disconnecting)

    def test_time_out(self):
        self.clock.advance(12)
        self.failUnless(self.transport.disconnecting)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir_path)


class ReadSessions(unittest.TestCase):
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
        self.rs = ReadSession(('127.0.0.1', 65465), self.reader, _clock=self.clock)
        self.rs.transport = self.transport
        self.rs.startProtocol()

    @inlineCallbacks
    def test_invalid_tid(self):
        data_datagram = DATADatagram(1, 'foobar')
        yield self.rs.datagramReceived(data_datagram.to_wire(), ('127.0.0.1', 1111))
        err_dgram = TFTPDatagramFactory(*split_opcode(self.transport.value()))
        self.assertEqual(err_dgram.errorcode, ERR_TID_UNKNOWN)
        self.addCleanup(self.rs.cancel)

    @inlineCallbacks
    def test_ERROR(self):
        err_dgram = ERRORDatagram.from_code(ERR_NOT_DEFINED, 'no reason')
        yield self.rs.datagramReceived(err_dgram.to_wire(), ('127.0.0.1', 65465))
        self.failIf(self.transport.value())
        self.failUnless(self.transport.disconnecting)

    @inlineCallbacks
    def test_ACK_invalid_blocknum(self):
        ack_datagram = ACKDatagram(3)
        yield self.rs.datagramReceived(ack_datagram.to_wire(), ('127.0.0.1', 65465))
        self.failIf(self.transport.disconnecting)
        err_dgram = TFTPDatagramFactory(*split_opcode(self.transport.value()))
        self.assert_(isinstance(err_dgram, ERRORDatagram))
        self.addCleanup(self.rs.cancel)

    @inlineCallbacks
    def test_ACK_stale_blocknum(self):
        self.rs.blocknum = 2
        ack_datagram = ACKDatagram(1)
        yield self.rs.datagramReceived(ack_datagram.to_wire(), ('127.0.0.1', 65465))
        self.failIf(self.transport.disconnecting)
        self.failIf(self.transport.value(),
                    "Stale ACK datagram, we should not write anything back")
        self.addCleanup(self.rs.cancel)

    def test_ACK(self):
        self.rs.block_size = 5
        self.rs.blocknum = 1
        ack_datagram = ACKDatagram(1)
        d = self.rs.datagramReceived(ack_datagram.to_wire(), ('127.0.0.1', 65465))
        def cb(ign):
            self.clock.advance(0.1)
            self.failIf(self.transport.disconnecting)
            data_datagram = TFTPDatagramFactory(*split_opcode(self.transport.value()))
            self.assertEqual(data_datagram.data, 'line1')
            self.failIf(self.rs.completed,
                        "Got enough bytes from the reader, there is no reason to stop")
        d.addCallback(cb)
        self.clock.advance(2.5)
        self.addCleanup(self.rs.cancel)
        return d

    def test_ACK_finished(self):
        self.rs.block_size = 512
        self.rs.blocknum = 1

        # Send a terminating datagram
        ack_datagram = ACKDatagram(1)
        d = self.rs.datagramReceived(ack_datagram.to_wire(), ('127.0.0.1', 65465))
        def cb(ign):
            self.clock.advance(0.1)
            ack_datagram = ACKDatagram(2)
            # This datagram doesn't trigger any sends
            self.rs.datagramReceived(ack_datagram.to_wire(), ('127.0.0.1', 65465))

            self.assertEqual(self.transport.value(), DATADatagram(2, self.test_data).to_wire())
            self.failUnless(self.rs.completed,
                        "Data length is less, than blocksize, time to stop")
        self.addCleanup(self.rs.cancel)
        d.addCallback(cb)
        self.clock.advance(3)
        return d

    def test_ACK_backoff(self):
        self.rs.block_size = 5
        self.rs.blocknum = 1

        ack_datagram = ACKDatagram(1)
        d = self.rs.datagramReceived(ack_datagram.to_wire(), ('127.0.0.1', 65465))
        def cb(ign):

            self.clock.pump((1,)*4)
            # Sent two times - initial send and a retransmit after first timeout
            self.assertEqual(self.transport.value(),
                             DATADatagram(2, self.test_data[:5]).to_wire()*2)

            # Sent three times - initial send and two retransmits
            self.clock.pump((1,)*5)
            self.assertEqual(self.transport.value(),
                             DATADatagram(2, self.test_data[:5]).to_wire()*3)

            # Sent still three times - initial send, two retransmits and the last wait
            self.clock.pump((1,)*10)
            self.assertEqual(self.transport.value(),
                             DATADatagram(2, self.test_data[:5]).to_wire()*3)

            self.failUnless(self.transport.disconnecting)
        d.addCallback(cb)
        self.clock.advance(2.5)
        return d

    @inlineCallbacks
    def test_failed_read(self):
        self.rs.reader = FailingReader()
        self.rs.blocknum = 1
        ack_datagram = ACKDatagram(1)
        yield self.rs.datagramReceived(ack_datagram.to_wire(), ('127.0.0.1', 65465))
        self.flushLoggedErrors()
        self.clock.advance(0.1)
        err_datagram = TFTPDatagramFactory(*split_opcode(self.transport.value()))
        self.failUnless(isinstance(err_datagram, ERRORDatagram))
        self.failUnless(self.transport.disconnecting)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir_path)


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
            self.failUnless(self.transport.value())
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

    def test_remote_origin_read_bootstrap(self):
        # First datagram
        self.rs.block_size = 5
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

    def test_remote_origin_write_bootstrap(self):
        # Initial ACK
        self.ws.startProtocol()
        ack_datagram_0 = ACKDatagram(0)
        self.assertEqual(self.transport.value(), ack_datagram_0.to_wire())
        self.failIf(self.transport.disconnecting)

        # Normal exchange
        self.transport.clear()
        d = self.ws.datagramReceived(DATADatagram(1, 'foobar'), ('127.0.0.1', 65465))
        def cb(res):
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
