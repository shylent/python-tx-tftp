'''
@author: shylent
'''
from tftp.datagram import (ACKDatagram, ERRORDatagram, ERR_TID_UNKNOWN,
    TFTPDatagramFactory, split_opcode, OP_DATA, OP_ERROR, ERR_ILLEGAL_OP,
    ERR_DISK_FULL, OP_ACK, DATADatagram, ERR_NOT_DEFINED)
from twisted.internet import reactor
from twisted.internet.defer import maybeDeferred
from twisted.internet.protocol import DatagramProtocol
from twisted.python import log
from tftp.util import SequentialCall


class WriteSession(DatagramProtocol):
    """Represents a transfer, during which we write to a local file. If we are a
    server, this means, that we received a WRQ (write request). If we are a client,
    this means, that we have requested a read from a remote server.

    @cvar block_size: Expected block size. If a data chunk is received and its length
    is less, than C{block_size}, it is assumed that that data chunk is the last in the
    transfer. Default: 512 (as per U{RFC1350<http://tools.ietf.org/html/rfc1350>})
    @type block_size: C{int}.

    @cvar timeout: a number of seconds to wait for the next data chunk. Default: 10
    @type timeout: C{int}

    """

    block_size = 512
    timeout = 10

    def __init__(self, remote, writer, _clock=None):
        self.writer = writer
        self.remote = remote
        self.blocknum = 0
        self.completed = False
        self.timeout_watchdog = None
        if _clock is None:
            self._clock = reactor
        else:
            self._clock = _clock

    def cancel(self):
        """Cancel this session, discard any data, that was collected
        and give up the connector.

        """
        if self.timeout_watchdog is not None:
            self.timeout_watchdog.cancel()
        self.writer.cancel()
        self.transport.stopListening()

    def startProtocol(self):
        """Enter "connected" mode and start the timeout watchdog"""
        addr = self.transport.getHost()
        log.msg("Write session started on %s, remote: %s" % (addr, self.remote))
        self.transport.connect(*self.remote)
        self._resetWatchdog(self.timeout)

    def connectionRefused(self):
        if not self.completed:
            self.writer.cancel()
        self.transport.stopListening()

    def datagramReceived(self, datagram, addr):
        if self.remote[1] != addr[1]:
            self.transport.write(ERRORDatagram.from_code(ERR_TID_UNKNOWN).to_wire())
            return # Does not belong to this transfer
        datagram = TFTPDatagramFactory(*split_opcode(datagram))
        log.msg("Datagram received from %s: %s" % (addr, datagram))
        if datagram.opcode == OP_DATA:
            return self.tftp_DATA(datagram)
        elif datagram.opcode == OP_ERROR:
            log.msg("Got error: " % datagram)
            self.cancel()

    def tftp_DATA(self, datagram):
        """Handle incoming DATA TFTP datagram

        @type datagram: L{DATADatagram}

        """
        next_blocknum = self.blocknum + 1
        if datagram.blocknum < next_blocknum:
            self.transport.write(ACKDatagram(datagram.blocknum).to_wire())
        elif datagram.blocknum == next_blocknum:
            if self.completed:
                self.transport.write(ERRORDatagram.from_code(
                    ERR_ILLEGAL_OP, "Transfer already finished").to_wire())
            else:
                return self.nextBlock(datagram)
        else:
            self.transport.write(ERRORDatagram.from_code(
                ERR_ILLEGAL_OP, "Block number mismatch").to_wire())

    def nextBlock(self, datagram):
        """Handle fresh data, attempt to write it to backend

        @type datagram: L{DATADatagram}

        """
        self._resetWatchdog(self.timeout)
        self.blocknum += 1
        d = maybeDeferred(self.writer.write, datagram.data)
        d.addCallbacks(callback=self.blockWriteSuccess, callbackArgs=[datagram, ],
                       errback=self.blockWriteFailure)
        return d

    def blockWriteSuccess(self, ign, datagram):
        """The write was successful, respond with ACK for current block number

        If this is the last chunk (received data length < block size), the protocol
        will keep running until the end of current timeout period, so we can respond
        to any duplicates.

        @type datagram: L{DATADatagram}

        """
        self.transport.write(ACKDatagram(datagram.blocknum).to_wire())
        if len(datagram.data) < self.block_size:
            self.completed = True
            self.writer.finish()

    def blockWriteFailure(self, failure):
        """Write failed"""
        log.err(failure)
        self.transport.write(ERRORDatagram.from_code(ERR_DISK_FULL).to_wire())
        self.cancel()

    def timedOut(self):
        """Called when the protocol has timed out. Let the backend know, if the
        the transfer was successful.

        """
        if not self.completed:
            log.msg("Timed out while waiting for next block")
            self.writer.cancel()
        else:
            log.msg("Timed out after a successful transfer")
        self.transport.stopListening()

    def _resetWatchdog(self, timeout):
        if self.timeout_watchdog is not None:
            self.timeout_watchdog.reset(timeout)
        else:
            self.timeout_watchdog = self._clock.callLater(timeout, self.timedOut)


class LocalOriginWriteSession(WriteSession):
    """Bootstraps a L{WriteSession}, that was initiated locally, - we've requested
    a read from a remote server

    @ivar handshake_timeout_watchdog: an object, responsible for terminating this
    session, if the initial data chunk has not been received. Set by the owner
    before this protocol's L{startProtocol} is called

    """
    def __init__(self, remote, writer, _clock=None):
        self.handshake_timeout_watchdog = None
        WriteSession.__init__(self, remote, writer, _clock)

    def startProtocol(self):
        """Start the L{handshake_timeout_watchdog} and hand over control to the
        actual L{WriteSession} protocol.

        """
        if self.handshake_timeout_watchdog is not None:
            self.handshake_timeout_watchdog.start()
        WriteSession.startProtocol(self)

    def nextBlock(self, datagram):
        """Initial DATA datagram has been received and the transfer is considered
        to have started successfully. Cancel the L{handshake_timeout_watchdog}

        """
        if self.handshake_timeout_watchdog.active():
            self.handshake_timeout_watchdog.cancel()
        return WriteSession.nextBlock(self, datagram)


class RemoteOriginWriteSession(WriteSession):
    """Bootstraps a L{WriteSession}, that was originated remotely, - we've
    received a WRQ from a client.

    """

    def startProtocol(self):
        """Respond with an initial ACK"""
        WriteSession.startProtocol(self)
        self.transport.write(ACKDatagram(self.blocknum).to_wire())


class ReadSession(DatagramProtocol):
    """Represents a transfer, during which we read from a local file
    (and write to the network). If we are a server, this means, that we've received
    a RRQ (read request). If we are a client, this means that we've requested to
    write to a remote server.

    @cvar block_size: The data will be sent in chunks of this size. If we send
    a chunk with the size < C{block_size}, the transfer will end.
    Default: 512 (as per U{RFC1350<http://tools.ietf.org/html/rfc1350>})
    @type block_size: C{int}

    @cvar timeout: An iterable, that yields timeout values for every subsequent
    unacknowledged DATADatagram, that we've sent. When (if) the iterable is exhausted,
    the transfer is considered failed.
    @type timeout: any iterable

    """
    block_size = 512
    timeout = (3, 5, 10)

    def __init__(self, remote, reader, _clock=None):
        self.remote = remote
        self.reader = reader
        self.blocknum = 0
        self.completed = False
        self.timeout_watchdog = None
        if _clock is None:
            self._clock = reactor
        else:
            self._clock = _clock

    def cancel(self):
        """Tell the reader to give up the resources. Stop the timeout cycle
        and disconnect the transport.

        """
        self.reader.finish()
        if self.timeout_watchdog is not None:
            self.timeout_watchdog.cancel()
        self.transport.stopListening()

    def startProtocol(self):
        """Enter "connected" mode"""
        addr = self.transport.getHost()
        log.msg("Read session started on %s, remote: %s" % (addr, self.remote))
        self.transport.connect(*self.remote)

    def connectionRefused(self):
        self.finish()

    def datagramReceived(self, datagram, addr):
        if self.remote[1] != addr[1]:
            self.transport.write(ERRORDatagram.from_code(ERR_TID_UNKNOWN).to_wire())
            return
        datagram = TFTPDatagramFactory(*split_opcode(datagram))
        log.msg("Datagram received from %s: %s" % (addr, datagram))
        if datagram.opcode == OP_ACK:
            return self.tftp_ACK(datagram)
        elif datagram.opcode == OP_ERROR:
            log.msg("Got error: " % datagram)
            self.cancel()

    def tftp_ACK(self, datagram):
        """Handle the incoming ACK TFTP datagram.

        @type datagram: L{ACKDatagram}

        """
        if datagram.blocknum < self.blocknum:
            log.msg("Duplicate ACK for blocknum %s" % datagram.blocknum)
        elif datagram.blocknum == self.blocknum:
            if self.timeout_watchdog is not None:
                self.timeout_watchdog.cancel()
            if self.completed:
                log.msg("Final ACK received, transfer successful")
                self.cancel()
            else:
                return self.nextBlock()
        else:
            self.transport.write(ERRORDatagram.from_code(
                ERR_ILLEGAL_OP, "Block number mismatch").to_wire())

    def nextBlock(self):
        """ACK datagram for the previous block has been received. Attempt to read
        the next block, that will be sent.

        """
        self.blocknum += 1
        d = maybeDeferred(self.reader.read, self.block_size)
        d.addCallbacks(callback=self.dataFromReader, errback=self.readFailed)
        return d

    def dataFromReader(self, data):
        """Got data from the reader. Send it to the network and start the timeout
        cycle.

        """
        if len(data) < self.block_size:
            self.completed = True
        bytes = DATADatagram(self.blocknum, data).to_wire()
        self.timeout_watchdog = SequentialCall.run(self.timeout[:-1],
            callable=self.sendData, callable_args=[bytes, ],
            on_timeout=lambda: self._clock.callLater(self.timeout[-1], self.timedOut),
            run_now=True,
            _clock=self._clock
        )

    def readFailed(self, fail):
        """The reader reported an error. Notify the remote end and cancel the transfer"""
        log.err(fail)
        self.transport.write(ERRORDatagram.from_code(ERR_NOT_DEFINED, "Read failed").to_wire())
        self.cancel()

    def timedOut(self):
        """Timeout iterable has been exhausted. End the transfer"""
        log.msg("Session timed out, last wait was %s seconds long" % self.timeout[-1])
        self.cancel()

    def sendData(self, bytes):
        self.transport.write(bytes)


class LocalOriginReadSession(ReadSession):
    """Bootstraps a L{ReadSession}, that was originated locally, - we've requested
    a write to a remote server.

    @ivar handshake_timeout_watchdog: an object, responsible for terminating this
    session, if the initial data chunk has not been received. Set by the owner
    before this protocol's L{startProtocol} is called

    """
    def __init__(self, remote, reader, _clock=None):
        self.handshake_timeout_watchdog = None
        ReadSession.__init__(self, remote, reader, _clock)

    def startProtocol(self):
        """Start the L{handshake_timeout_watchdog} and hand over control to
        L{ReadSession}.

        """
        if self.handshake_timeout_watchdog is not None:
            self.handshake_timeout_watchdog.start()
        ReadSession.startProtocol(self)

    def nextBlock(self):
        """An initial ACK datagram has been received, the transfer has started.
        Cancel the L{handshake_timeout_watchdog}

        """
        if (self.handshake_timeout_watchdog is not None and
                self.handshake_timeout_watchdog.active()):
            self.handshake_timeout_watchdog.cancel()
        return ReadSession.nextBlock(self)


class RemoteOriginReadSession(ReadSession):
    """Bootstraps a L{ReadSession}, that was started remotely, - we've received
    a RRQ.

    """

    def startProtocol(self):
        """Initialize the L{ReadSession} and make it send the first data chunk."""
        ReadSession.startProtocol(self)
        return self.nextBlock()
