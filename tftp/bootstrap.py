'''
@author: shylent
'''
from tftp.datagram import (ACKDatagram, ERRORDatagram, ERR_TID_UNKNOWN, 
    TFTPDatagramFactory, split_opcode, OP_OACK, OP_ERROR, OACKDatagram, OP_ACK, 
    OP_DATA)
from tftp.session import WriteSession, MAX_BLOCK_SIZE, ReadSession
from tftp.util import SequentialCall
from twisted.internet import reactor
from twisted.internet.defer import maybeDeferred
from twisted.internet.protocol import DatagramProtocol
from twisted.python import log
from twisted.python.util import OrderedDict

class TFTPBootstrap(DatagramProtocol):
    
    def __init__(self, remote, options=None, _clock=None):
        self.options = options
        self.remote = remote
        self.timeout_watchdog = None
        if _clock is not None:
            self._clock = _clock
        else:
            self._clock = reactor
    
    def processOptions(self, options):
        accepted_options = OrderedDict()
        for name, val in options.iteritems():
            if name in self.supported_options:
                actual_value = getattr(self, 'option_' + name)(val)
                if actual_value is not None:
                    accepted_options[name] = actual_value
        return accepted_options

    def option_blksize(self, val):
        try:
            int_blksize = int(val)
        except ValueError:
            return None
        if int_blksize < 8 or int_blksize > 65464:
            return None
        int_blksize = max((int_blksize, MAX_BLOCK_SIZE))
        self.session.block_size = int_blksize
        return str(int_blksize)


class LocalOriginWriteSession(TFTPBootstrap):
    """Bootstraps a L{WriteSession}, that was initiated locally, - we've requested
    a read from a remote server

    @ivar handshake_timeout_watchdog: an object, responsible for terminating this
    session, if the initial data chunk has not been received. Set by the owner
    before this protocol's L{startProtocol} is called

    """
    def __init__(self, remote, writer, options=None, _clock=None):
        TFTPBootstrap.__init__(self, remote, options, _clock)
        self.writer = writer
        self.session = WriteSession(writer, self._clock)

    def startProtocol(self):
        """Start the L{handshake_timeout_watchdog} and hand over control to the
        actual L{WriteSession} protocol.

        """
        self.transport.connect(*self.remote)
        if self.handshake_timeout_watchdog is not None:
            self.handshake_timeout_watchdog.start()

    def tftp_OACK(self, datagram):
        if not self.session.started:
            options = self.processOptions(datagram.options)
            if self.handshake_timeout_watchdog.active():
                self.handshake_timeout_watchdog.cancel()
            return self.transport.write(ACKDatagram(0))
        else:
            log.msg("Duplicate OACK received, send back ACK and ignore")
            self.transport.write(ACKDatagram(0))

    def datagramReceived(self, datagram, addr):
        if self.remote[1] != addr[1]:
            self.transport.write(ERRORDatagram.from_code(ERR_TID_UNKNOWN).to_wire())
            return # Does not belong to this transfer
        datagram = TFTPDatagramFactory(*split_opcode(datagram))
        log.msg("Datagram received from %s: %s" % (addr, datagram))
        if datagram.opcode == OP_ERROR:
            if self.session.started:
                return self.session.datagramReceived(datagram)
            else:
                log.msg("Got error: " % datagram)
                return self.cancel()
        elif datagram.opcode == OP_OACK:
            return self.tftp_OACK(datagram)
        elif datagram.opcode == OP_DATA and datagram.blocknum == 1:
            if self.handshake_timeout_watchdog.active():
                self.handshake_timeout_watchdog.cancel()
            if not self.session.started:
                self.session.transport = self.transport
                self.session.startProtocol()
            return self.session.datagramReceived(datagram)
        elif self.session.started:
            return self.session.datagramReceived(datagram)

    def cancel(self):
        if self.session.started:
            return self.session.cancel()
        else:
            self.writer.cancel()
            self.transport.stopListening()


class RemoteOriginWriteSession(TFTPBootstrap):
    """Bootstraps a L{WriteSession}, that was originated remotely, - we've
    received a WRQ from a client.

    """
    supported_options = ('blksize',)

    def __init__(self, remote, writer, options=None, _clock=None):
        TFTPBootstrap.__init__(self, remote, options, _clock)
        self.writer = writer
        self.session = WriteSession(writer, self._clock)

    def startProtocol(self):
        """Respond with an initial ACK"""
        self.transport.connect(*self.remote)
        if self.options is not None:
            options = self.processOptions(self.options)
            datagram = OACKDatagram(options)
        else:
            datagram = ACKDatagram(0)
        self._clock.callLater(0, self.transport.write, datagram.to_wire())
        self.session.transport = self.transport
        return self.session.startProtocol()

    def datagramReceived(self, datagram, addr):
        if self.remote[1] != addr[1]:
            self.transport.write(ERRORDatagram.from_code(ERR_TID_UNKNOWN).to_wire())
            return # Does not belong to this transfer
        datagram = TFTPDatagramFactory(*split_opcode(datagram))
        log.msg("Datagram received from %s: %s" % (addr, datagram))
        return self.session.datagramReceived(datagram)

    def cancel(self):
        if self.session.started:
            self.session.cancel()
        else:
            self.writer.cancel()
            self.transport.stopListening()


class LocalOriginReadSession(TFTPBootstrap):
    """Bootstraps a L{ReadSession}, that was originated locally, - we've requested
    a write to a remote server.

    @ivar handshake_timeout_watchdog: an object, responsible for terminating this
    session, if the initial data chunk has not been received. Set by the owner
    before this protocol's L{startProtocol} is called

    """
    def __init__(self, remote, reader, options=None, _clock=None):
        TFTPBootstrap.__init__(self, remote, options, _clock)
        self.reader = reader
        self.session = ReadSession(reader, self._clock)

    def startProtocol(self):
        """Start the L{handshake_timeout_watchdog} and hand over control to
        L{ReadSession}.

        """
        self.transport.connect(*self.remote)
        if self.handshake_timeout_watchdog is not None:
            self.handshake_timeout_watchdog.start()

    def datagramReceived(self, datagram, addr):
        if self.remote[1] != addr[1]:
            self.transport.write(ERRORDatagram.from_code(ERR_TID_UNKNOWN).to_wire())
            return # Does not belong to this transfer
        datagram = TFTPDatagramFactory(*split_opcode(datagram))
        log.msg("Datagram received from %s: %s" % (addr, datagram))
        if datagram.opcode == OP_OACK:
            return self.tftp_OACK(datagram)
        elif (datagram.opcode == OP_ACK and datagram.blocknum == 0
                    and not self.session.started):
            self.session.transport = self.transport
            self.session.startProtocol()
            if self.handshake_timeout_watchdog is not None:
                self.handshake_timeout_watchdog.cancel()
            return self.session.nextBlock()
        elif datagram.opcode == OP_ERROR:
            if self.session.started:
                return self.session.datagramReceived(datagram)
            else:
                log.msg("Got error: " % datagram)
                return self.cancel()
        elif self.session.started:
            return self.session.datagramReceived(datagram)

    def tftp_OACK(self, datagram):
        if not self.session.started:
            options = self.processOptions(datagram.options)
            if self.handshake_timeout_watchdog is not None:
                self.handshake_timeout_watchdog.cancel()
            self.session.transport = self.transport
            self.session.startProtocol()
            return self.session.nextBlock()
        else:
            log.msg("Duplicate OACK received, ignored")

    def cancel(self):
        if self.session.started:
            self.session.cancel()
        else:
            if self.handshake_timeout_watchdog is not None:
                self.handshake_timeout_watchdog.cancel()
            self.reader.finish()
            self.transport.stopListening()


class RemoteOriginReadSession(TFTPBootstrap):
    """Bootstraps a L{ReadSession}, that was started remotely, - we've received
    a RRQ.

    """
    timeout = (1, 3, 5)

    def __init__(self, remote, reader, options=None, _clock=None):
        TFTPBootstrap.__init__(self, remote, options, _clock)
        self.reader = reader
        self.handshake_timeout_watchdog = None
        self.session = ReadSession(reader, self._clock)

    def datagramReceived(self, datagram, addr):
        if self.remote[1] != addr[1]:
            self.transport.write(ERRORDatagram.from_code(ERR_TID_UNKNOWN).to_wire())
            return # Does not belong to this transfer
        datagram = TFTPDatagramFactory(*split_opcode(datagram))
        log.msg("Datagram received from %s: %s" % (addr, datagram))
        if datagram.opcode == OP_ACK and datagram.blocknum == 0:
            return self.tftp_ACK(datagram)
        elif datagram.opcode == OP_ERROR:
            if self.session.started:
                return self.session.datagramReceived(datagram)
            else:
                log.msg("Got error: " % datagram)
                return self.cancel()
        elif self.session.started:
            return self.session.datagramReceived(datagram)

    def tftp_ACK(self, datagram):
        if self.timeout_watchdog is not None:
            self.timeout_watchdog.cancel()
        if not self.session.started:
            self.session.transport = self.transport
            self.session.startProtocol()
            return self.session.nextBlock()

    def startProtocol(self):
        """Initialize the L{ReadSession} and make it send the first data chunk."""
        self.transport.connect(*self.remote)
        if self.options is not None:
            options = self.processOptions(self.options)
            oack_dgram = OACKDatagram(options)
            self.timeout_watchdog = SequentialCall.run(
                self.timeout[:-1],
                callable=self.sendData, callable_args=[oack_dgram.to_wire(), ],
                on_timeout=lambda: self._clock.callLater(self.timeout[-1], self.timedOut),
                run_now=True,
                _clock=self._clock
            )
        else:
            self.session.transport = self.transport
            self.session.startProtocol()
            return self.session.nextBlock()

    def sendData(self, bytes):
        self.transport.write(bytes)

    def timedOut(self):
        log.msg("Timed during option negotiation process")
        self.cancel()

    def cancel(self):
        if self.session.started:
            self.session.cancel()
        else:
            if self.timeout_watchdog is not None:
                self.timeout_watchdog.cancel()
            self.reader.finish()
            self.transport.stopListening()
