'''
@author: shylent
'''
from tftp.datagram import (ACKDatagram, ERRORDatagram, ERR_TID_UNKNOWN,
    TFTPDatagramFactory, split_opcode, OP_OACK, OP_ERROR, OACKDatagram, OP_ACK,
    OP_DATA)
from tftp.session import WriteSession, MAX_BLOCK_SIZE, ReadSession
from tftp.util import SequentialCall
from twisted.internet import reactor
from twisted.internet.protocol import DatagramProtocol
from twisted.python import log
from twisted.python.util import OrderedDict

class TFTPBootstrap(DatagramProtocol):
    supported_options = ('blksize', 'timeout')

    def __init__(self, remote, backend, options=None, _clock=None):
        self.options = options
        self.resultant_options = OrderedDict()
        self.remote = remote
        self.timeout_watchdog = None
        self.backend = backend
        if _clock is not None:
            self._clock = _clock
        else:
            self._clock = reactor

    def processOptions(self, options):
        accepted_options = OrderedDict()
        for name, val in options.iteritems():
            norm_name = name.lower()
            if norm_name in self.supported_options:
                actual_value = getattr(self, 'option_' + norm_name)(val)
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
        int_blksize = min((int_blksize, MAX_BLOCK_SIZE))
        return str(int_blksize)

    def option_timeout(self, val):
        try:
            int_timeout = int(val)
        except ValueError:
            return None
        if int_timeout < 1 or int_timeout > 255:
            return None
        return str(int_timeout)

    def applyOptions(self, session, options):
        for opt_name, opt_val in options.iteritems():
            if opt_name == 'blksize':
                session.block_size = int(opt_val)
            elif opt_name == 'timeout':
                timeout = int(opt_val)
                session.timeout = (timeout,) * 3

    def tftp_ERROR(self, datagram):
        log.msg("Got error: " % datagram)
        return self.cancel()

    def cancel(self):
        if self.timeout_watchdog is not None and self.timeout_watchdog.active():
            self.timeout_watchdog.cancel()
        if self.session.started:
            self.session.cancel()
        else:
            self.backend.finish()
            self.transport.stopListening()
    
    def timedOut(self):
        log.msg("Timed during option negotiation process")
        self.cancel()


class LocalOriginWriteSession(TFTPBootstrap):
    """Bootstraps a L{WriteSession}, that was initiated locally, - we've requested
    a read from a remote server

    @ivar timeout_watchdog: an object, responsible for terminating this
    session, if the initial data chunk has not been received. Set by the owner
    before this protocol's L{startProtocol} is called

    """
    def __init__(self, remote, writer, options=None, _clock=None):
        TFTPBootstrap.__init__(self, remote, writer, options, _clock)
        self.session = WriteSession(writer, self._clock)

    def startProtocol(self):
        """Start the L{timeout_watchdog} and hand over control to the
        actual L{WriteSession} protocol.

        """
        self.transport.connect(*self.remote)
        if self.timeout_watchdog is not None:
            self.timeout_watchdog.start()

    def tftp_OACK(self, datagram):
        if not self.session.started:
            self.resultant_options = self.processOptions(datagram.options)
            if self.timeout_watchdog.active():
                self.timeout_watchdog.cancel()
            return self.transport.write(ACKDatagram(0).to_wire())
        else:
            log.msg("Duplicate OACK received, send back ACK and ignore")
            self.transport.write(ACKDatagram(0).to_wire())

    def datagramReceived(self, datagram, addr):
        if self.remote[1] != addr[1]:
            self.transport.write(ERRORDatagram.from_code(ERR_TID_UNKNOWN).to_wire())
            return # Does not belong to this transfer
        datagram = TFTPDatagramFactory(*split_opcode(datagram))
        log.msg("Datagram received from %s: %s" % (addr, datagram))
        if datagram.opcode == OP_ERROR:
            return self.tftp_ERROR(datagram)
        elif datagram.opcode == OP_OACK:
            return self.tftp_OACK(datagram)
        elif datagram.opcode == OP_DATA and datagram.blocknum == 1:
            if self.timeout_watchdog is not None and self.timeout_watchdog.active():
                self.timeout_watchdog.cancel()
            if not self.session.started:
                self.applyOptions(self.session, self.resultant_options)
                self.session.transport = self.transport
                self.session.startProtocol()
            return self.session.datagramReceived(datagram)
        elif self.session.started:
            return self.session.datagramReceived(datagram)


class RemoteOriginWriteSession(TFTPBootstrap):
    """Bootstraps a L{WriteSession}, that was originated remotely, - we've
    received a WRQ from a client.

    """
    timeout = (1, 3, 7)

    def __init__(self, remote, writer, options=None, _clock=None):
        TFTPBootstrap.__init__(self, remote, writer, options, _clock)
        self.session = WriteSession(writer, self._clock)

    def startProtocol(self):
        """Respond with an initial ACK"""
        self.transport.connect(*self.remote)
        if self.options is not None:
            self.resultant_options = self.processOptions(self.options)
            bytes = OACKDatagram(self.resultant_options).to_wire()
        else:
            bytes = ACKDatagram(0).to_wire()
        self.timeout_watchdog = SequentialCall.run(
            self.timeout[:-1],
            callable=self.transport.write, callable_args=[bytes, ],
            on_timeout=lambda: self._clock.callLater(self.timeout[-1], self.timedOut),
            run_now=True,
            _clock=self._clock
        )

    def datagramReceived(self, datagram, addr):
        if self.remote[1] != addr[1]:
            self.transport.write(ERRORDatagram.from_code(ERR_TID_UNKNOWN).to_wire())
            return # Does not belong to this transfer
        datagram = TFTPDatagramFactory(*split_opcode(datagram))
        log.msg("Datagram received from %s: %s" % (addr, datagram))
        if datagram.opcode == OP_ERROR:
            return self.tftp_ERROR(datagram)
        elif datagram.opcode == OP_DATA and datagram.blocknum == 1:
            if self.timeout_watchdog.active():
                self.timeout_watchdog.cancel()
            if not self.session.started:
                self.applyOptions(self.session, self.resultant_options)
                self.session.transport = self.transport
                self.session.startProtocol()
            return self.session.datagramReceived(datagram)
        elif self.session.started:
            return self.session.datagramReceived(datagram)


class LocalOriginReadSession(TFTPBootstrap):
    """Bootstraps a L{ReadSession}, that was originated locally, - we've requested
    a write to a remote server.

    @ivar timeout_watchdog: an object, responsible for terminating this
    session, if the initial data chunk has not been received. Set by the owner
    before this protocol's L{startProtocol} is called

    """
    def __init__(self, remote, reader, options=None, _clock=None):
        TFTPBootstrap.__init__(self, remote, reader, options, _clock)
        self.session = ReadSession(reader, self._clock)

    def startProtocol(self):
        """Start the L{timeout_watchdog} and hand over control to
        L{ReadSession}.

        """
        self.transport.connect(*self.remote)
        if self.timeout_watchdog is not None:
            self.timeout_watchdog.start()

    def datagramReceived(self, datagram, addr):
        if self.remote[1] != addr[1]:
            self.transport.write(ERRORDatagram.from_code(ERR_TID_UNKNOWN).to_wire())
            return # Does not belong to this transfer
        datagram = TFTPDatagramFactory(*split_opcode(datagram))
        log.msg("Datagram received from %s: %s" % (addr, datagram))
        if datagram.opcode == OP_ERROR:
            return self.tftp_ERROR(datagram)
        elif datagram.opcode == OP_OACK:
            return self.tftp_OACK(datagram)
        elif (datagram.opcode == OP_ACK and datagram.blocknum == 0
                    and not self.session.started):
            self.session.transport = self.transport
            self.session.startProtocol()
            if self.timeout_watchdog is not None and self.timeout_watchdog.active():
                self.timeout_watchdog.cancel()
            return self.session.nextBlock()
        elif self.session.started:
            return self.session.datagramReceived(datagram)

    def tftp_OACK(self, datagram):
        if not self.session.started:
            self.resultant_options = self.processOptions(datagram.options)
            if self.timeout_watchdog is not None and self.timeout_watchdog.active():
                self.timeout_watchdog.cancel()
            self.applyOptions(self.session, self.resultant_options)
            self.session.transport = self.transport
            self.session.startProtocol()
            return self.session.nextBlock()
        else:
            log.msg("Duplicate OACK received, ignored")

class RemoteOriginReadSession(TFTPBootstrap):
    """Bootstraps a L{ReadSession}, that was started remotely, - we've received
    a RRQ.

    """
    timeout = (1, 3, 7)

    def __init__(self, remote, reader, options=None, _clock=None):
        TFTPBootstrap.__init__(self, remote, reader, options, _clock)
        self.session = ReadSession(reader, self._clock)

    def startProtocol(self):
        """Initialize the L{ReadSession} and make it send the first data chunk."""
        self.transport.connect(*self.remote)
        if self.options is not None:
            self.resultant_options = self.processOptions(self.options)
            bytes = OACKDatagram(self.resultant_options).to_wire()
            self.timeout_watchdog = SequentialCall.run(
                self.timeout[:-1],
                callable=self.transport.write, callable_args=[bytes, ],
                on_timeout=lambda: self._clock.callLater(self.timeout[-1], self.timedOut),
                run_now=True,
                _clock=self._clock
            )
        else:
            self.session.transport = self.transport
            self.session.startProtocol()
            return self.session.nextBlock()

    def datagramReceived(self, datagram, addr):
        if self.remote[1] != addr[1]:
            self.transport.write(ERRORDatagram.from_code(ERR_TID_UNKNOWN).to_wire())
            return # Does not belong to this transfer
        datagram = TFTPDatagramFactory(*split_opcode(datagram))
        log.msg("Datagram received from %s: %s" % (addr, datagram))
        if datagram.opcode == OP_ERROR:
            return self.tftp_ERROR(datagram)
        elif datagram.opcode == OP_ACK and datagram.blocknum == 0:
            return self.tftp_ACK(datagram)
        elif self.session.started:
            return self.session.datagramReceived(datagram)

    def tftp_ACK(self, datagram):
        if self.timeout_watchdog is not None:
            self.timeout_watchdog.cancel()
        if not self.session.started:
            self.applyOptions(self.session, self.resultant_options)
            self.session.transport = self.transport
            self.session.startProtocol()
            return self.session.nextBlock()
