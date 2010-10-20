'''
@author: shylent
'''
from tftp.backend import FilesystemWriter, FilesystemReader
from tftp.datagram import (ACKDatagram, ERRORDatagram, ERR_TID_UNKNOWN,
    ERR_NOT_DEFINED, DATADatagram, TFTPDatagramFactory, split_opcode)
from tftp.session import WriteSession, ReadSession
from twisted.internet import reactor
from twisted.internet.defer import Deferred
from twisted.internet.task import Clock
from twisted.python.filepath import FilePath
from twisted.test.proto_helpers import StringTransport
from twisted.trial import unittest
import shutil
import tempfile


class FakeTransport(StringTransport):
    stopListening = StringTransport.loseConnection

    def connect(self, host, port):
        self._connectedAddr = (host, port)


class WriteSessions(unittest.TestCase):

    port = 65466

    def setUp(self):
        self.tmp_dir_path = tempfile.mkdtemp()
        self.target = FilePath(self.tmp_dir_path).child('foo')
        self.writer = FilesystemWriter(self.target)
        self.transport = FakeTransport(hostAddress=('127.0.0.1', self.port))
        self.ws = WriteSession(('127.0.0.1', 65465), self.writer)
        self.ws.timeout = 2
        self.ws.transport = self.transport
        self.ws.startProtocol()

    def test_invalid_tid(self):
        bad_tid_dgram = ACKDatagram(123)
        self.ws.datagramReceived(bad_tid_dgram.to_wire(), ('127.0.0.1', 1111))
        err_dgram = TFTPDatagramFactory(*split_opcode(self.transport.value()))
        self.assertEqual(err_dgram.errorcode, ERR_TID_UNKNOWN)
        self.addCleanup(self.ws.cancel)

    def test_ERROR(self):
        err_dgram = ERRORDatagram.from_code(ERR_NOT_DEFINED, 'no reason')
        self.ws.datagramReceived(err_dgram.to_wire(), ('127.0.0.1', 65465))
        self.failIf(self.transport.value())
        self.failUnless(self.transport.disconnecting)

    def test_DATA_stale_blocknum(self):
        self.ws.block_size = 6
        self.ws.blocknum = 2
        data_datgram = DATADatagram(1, 'foobar')
        self.ws.datagramReceived(data_datgram.to_wire(), ('127.0.0.1', 65465))
        self.writer.finish()
        self.failIf(self.target.open('r').read())
        self.failIf(self.transport.disconnecting)
        ack_dgram = TFTPDatagramFactory(*split_opcode(self.transport.value()))
        self.assertEqual(ack_dgram.blocknum, 1)
        self.addCleanup(self.ws.cancel)

    def test_DATA_invalid_blocknum(self):
        self.ws.block_size = 6
        data_datgram = DATADatagram(3, 'foobar')
        self.ws.datagramReceived(data_datgram.to_wire(), ('127.0.0.1', 65465))
        self.writer.finish()
        self.failIf(self.target.open('r').read())
        self.failIf(self.transport.disconnecting)
        err_dgram = TFTPDatagramFactory(*split_opcode(self.transport.value()))
        self.assert_(isinstance(err_dgram, ERRORDatagram))
        self.addCleanup(self.ws.cancel)

    def test_DATA(self):
        self.ws.block_size = 6
        data_datgram = DATADatagram(1, 'foobar')
        self.ws.datagramReceived(data_datgram.to_wire(), ('127.0.0.1', 65465))
        self.writer.finish()
        self.assertEqual(self.target.open('r').read(), 'foobar')
        self.failIf(self.transport.disconnecting)
        ack_dgram = TFTPDatagramFactory(*split_opcode(self.transport.value()))
        self.failUnless(isinstance(ack_dgram, ACKDatagram))
        self.failIf(self.ws.completed,
                    "Data length is equal to blocksize, no reason to stop")
        self.addCleanup(self.ws.cancel)

    def test_DATA_finished(self):
        self.ws.block_size = 6
        self.ws.timeout = 1

        # Send a terminating datagram
        data_datgram = DATADatagram(1, 'foo')
        self.ws.datagramReceived(data_datgram.to_wire(), ('127.0.0.1', 65465))
        self.assertEqual(self.target.open('r').read(), 'foo')
        ack_dgram = TFTPDatagramFactory(*split_opcode(self.transport.value()))
        self.failUnless(isinstance(ack_dgram, ACKDatagram))
        self.failUnless(self.ws.completed,
                    "Data length is less, than blocksize, time to stop")
        self.transport.clear()

        # Send another datagram after the transfer is considered complete
        data_datgram = DATADatagram(2, 'foobar')
        self.ws.datagramReceived(data_datgram.to_wire(), ('127.0.0.1', 65465))
        self.assertEqual(self.target.open('r').read(), 'foo')
        err_dgram = TFTPDatagramFactory(*split_opcode(self.transport.value()))
        self.failUnless(isinstance(err_dgram, ERRORDatagram))

        # Check for proper disconnection after grace timeout expires
        #FIXME: this should be done using twisted.internet.task.Clock
        d = Deferred()
        d.addCallback(lambda ign: self.failUnless(self.transport.disconnecting,
            "We are done and the grace timeout is over, should disconnect"))
        reactor.callLater(2., d.callback, None)
        return d

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
        self.reader = FilesystemReader(self.target)
        self.transport = FakeTransport(hostAddress=('127.0.0.1', self.port))
        self.rs = ReadSession(('127.0.0.1', 65465), self.reader, _clock=self.clock)
        self.rs.transport = self.transport
        self.rs.startProtocol()

    def test_invalid_tid(self):
        data_datgram = DATADatagram(1, 'foobar')
        self.rs.datagramReceived(data_datgram.to_wire(), ('127.0.0.1', 1111))
        err_dgram = TFTPDatagramFactory(*split_opcode(self.transport.value()))
        self.assertEqual(err_dgram.errorcode, ERR_TID_UNKNOWN)
        self.addCleanup(self.rs.cancel)

    def test_ERROR(self):
        err_dgram = ERRORDatagram.from_code(ERR_NOT_DEFINED, 'no reason')
        self.rs.datagramReceived(err_dgram.to_wire(), ('127.0.0.1', 65465))
        self.failIf(self.transport.value())
        self.failUnless(self.transport.disconnecting)

    def test_ACK_invalid_blocknum(self):
        ack_datgram = ACKDatagram(3)
        self.rs.datagramReceived(ack_datgram.to_wire(), ('127.0.0.1', 65465))
        self.failIf(self.transport.disconnecting)
        err_dgram = TFTPDatagramFactory(*split_opcode(self.transport.value()))
        self.assert_(isinstance(err_dgram, ERRORDatagram))
        self.addCleanup(self.rs.cancel)

    def test_ACK_stale_blocknum(self):
        self.rs.blocknum = 2
        ack_datgram = ACKDatagram(1)
        self.rs.datagramReceived(ack_datgram.to_wire(), ('127.0.0.1', 65465))
        self.failIf(self.transport.disconnecting)
        self.failIf(self.transport.value(),
                    "Stale ACK datagram, we should not write anything back")
        self.addCleanup(self.rs.cancel)

    def test_ACK(self):
        self.rs.block_size = 5
        self.rs.blocknum = 1
        ack_datgram = ACKDatagram(1)
        self.rs.datagramReceived(ack_datgram.to_wire(), ('127.0.0.1', 65465))
        self.clock.advance(0.1)
        self.failIf(self.transport.disconnecting)
        data_datagram = TFTPDatagramFactory(*split_opcode(self.transport.value()))
        self.assertEqual(data_datagram.data, 'line1')
        self.failIf(self.rs.completed,
                    "Got engough bytes from the reader, there is no reason to stop")
        self.addCleanup(self.rs.cancel)

    def test_ACK_finished(self):
        self.rs.block_size = 512
        self.rs.blocknum = 1

        # Send a terminating datagram
        ack_datgram = ACKDatagram(1)
        self.rs.datagramReceived(ack_datgram.to_wire(), ('127.0.0.1', 65465))
        self.clock.advance(0.1)
        ack_datgram = ACKDatagram(2)
        self.rs.datagramReceived(ack_datgram.to_wire(), ('127.0.0.1', 65465))
        self.clock.advance(0.1)

        self.assertEqual(self.transport.value(), DATADatagram(2, self.test_data).to_wire())
        self.failUnless(self.rs.completed,
                    "Data length is less, than blocksize, time to stop")
        self.addCleanup(self.rs.cancel)

    def test_ACK_backoff(self):
        self.rs.block_size = 5
        self.rs.blocknum = 1

        ack_datgram = ACKDatagram(1)
        self.rs.datagramReceived(ack_datgram.to_wire(), ('127.0.0.1', 65465))

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


    def tearDown(self):
        shutil.rmtree(self.tmp_dir_path)
