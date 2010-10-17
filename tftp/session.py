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


class WriteSession(DatagramProtocol):

    block_size = 512
    timeout = 10

    def __init__(self, remote, writer):
        self.writer = writer
        self.remote = remote
        self.blocknum = 0
        self.completed = False
        self.timeout_watchdog = None

    def _resetWatchdog(self, timeout):
        if self.timeout_watchdog is not None:
            self.timeout_watchdog.reset(timeout)
        else:
            self.timeout_watchdog = reactor.callLater(timeout, self.timedOut)

    def cancel(self):
        if self.timeout_watchdog is not None:
            self.timeout_watchdog.cancel()
        self.writer.cancel()
        self.transport.stopListening()

    def startProtocol(self):
        addr = self.transport.getHost()
        log.msg("Write session started on %s, remote: %s" % (addr, self.remote))
        self.transport.connect(*self.remote)
        self._resetWatchdog(self.timeout)

    def datagramReceived(self, datagram, addr):
        if self.remote[1] != addr[1]:
            self.transport.write(ERRORDatagram.from_code(ERR_TID_UNKNOWN).to_wire())
            return # Does not belong to this transfer
        datagram = TFTPDatagramFactory(*split_opcode(datagram))
        log.msg("Datagram received from %s: %s" % (addr, datagram))
        if datagram.opcode == OP_DATA:
            self.tftp_DATA(datagram)
        elif datagram.opcode == OP_ERROR:
            log.msg("Got error: " % datagram)
            self.cancel()

    def tftp_DATA(self, datagram):
        next_blocknum = self.blocknum + 1
        if datagram.blocknum < next_blocknum:
            self.transport.write(ACKDatagram(datagram.blocknum).to_wire())
        elif datagram.blocknum == next_blocknum:
            if self.completed:
                self.transport.write(ERRORDatagram.from_code(
                    ERR_ILLEGAL_OP, "Transfer already finished").to_wire())
            else:
                self.nextBlock(datagram)
        else:
            self.transport.write(ERRORDatagram.from_code(
                ERR_ILLEGAL_OP, "Block number mismatch").to_wire())

    def nextBlock(self, datagram):
        self._resetWatchdog(self.timeout)
        self.blocknum += 1
        d = maybeDeferred(self.writer.write, datagram.data)
        d.addCallbacks(callback=self.blockWriteSuccess, callbackArgs=[datagram, ],
                       errback=self.blockWriteFailure)
        return d

    def blockWriteFailure(self, failure):
        log.err("Failed to write to the local file", failure)
        self.transport.write(ERRORDatagram.from_code(ERR_DISK_FULL).to_wire())
        self.cancel()

    def blockWriteSuccess(self, ign, datagram):
        self.transport.write(ACKDatagram(datagram.blocknum).to_wire())
        if len(datagram.data) < self.block_size:
            self.completed = True
            self.writer.finish()

    def timedOut(self):
        if not self.completed:
            log.msg("Timed out while waiting for next block")
            self.writer.cancel()
        else:
            log.msg("Timed out after a successful transfer")
        self.transport.stopListening()


class LocalOriginWriteSession(WriteSession):

    def __init__(self, remote, writer, handshake_timeout_watchdog):
        self._handshake_timeout_watchdog = handshake_timeout_watchdog
        WriteSession.__init__(self, remote, writer)

    def nextBlock(self, datagram):
        if self._handshake_timeout_watchdog.active():
            self._handshake_timeout_watchdog.cancel()
        WriteSession.nextBlock(self, datagram)


class RemoteOriginWriteSession(WriteSession):

    def startProtocol(self):
        WriteSession.startProtocol(self)
        self.transport.write(ACKDatagram(self.blocknum).to_wire())


class ReadSession(DatagramProtocol):
    block_size = 512
    timeout = (3, 5, 10)

    def __init__(self, remote, reader):
        self.remote = remote
        self.reader = reader
        self.blocknum = 0
        self.completed = False
        self.timeout_watchdog = None

    def startProtocol(self):
        addr = self.transport.getHost()
        log.msg("Read session started on %s, remote: %s" % (addr, self.remote))
        self.transport.connect(*self.remote)

    def datagramReceived(self, datagram, addr):
        if self.remote[1] != addr[1]:
            self.transport.write(ERRORDatagram.from_code(ERR_TID_UNKNOWN).to_wire())
            return
        datagram = TFTPDatagramFactory(*split_opcode(datagram))
        log.msg("Datagram received from %s: %s" % (addr, datagram))
        if datagram.opcode == OP_ACK:
            self.tftp_ACK(datagram)
        elif datagram.opcode == OP_ERROR:
            log.msg("Got error: " % datagram)
            self.transport.stopListening()

    def tftp_ACK(self, datagram):
        if datagram.blocknum < self.blocknum:
            log.msg("Duplicate ACK for blocknum %s" % datagram.blocknum)
        elif datagram.blocknum == self.blocknum:
            if self.timeout_watchdog.active():
                self.timeout_watchdog.cancel()
            if self.completed:
                log.msg("Final ACK received, transfer successful")
                self.transport.stopListening()
            else:
                self.nextBlock()
        else:
            self.transport.write(ERRORDatagram.from_code(
                ERR_ILLEGAL_OP, "Block number mismatch").to_wire())

    def nextBlock(self):
        self.blocknum += 1
        d = maybeDeferred(self.reader.read, self.block_size)
        d.addCallbacks(callback=self.dataFromReader,
                       errback=self.readFailed)
        return d

    def dataFromReader(self, data):
        if len(data) < self.block_size:
            self.completed = True
        bytes = DATADatagram(self.blocknum, data).to_wire()
        self.timeout_watchdog = reactor.callLater(self.timeout[0],
                                                  self.retrySendData, bytes, 0)
        self.sendData(bytes)

    def retrySendData(self, bytes, timeout_ind):
        next_timeout_ind = timeout_ind + 1
        try:
            next_timeout = self.timeout[next_timeout_ind]
        except IndexError:
            log.msg("Session timed out, last wait was %s seconds long" %
                        self.timeout[timeout_ind])
            self.transport.stopListening()
        else:
            log.msg("Retrying after the %s second wait" % self.timeout[timeout_ind])
            self.timeout_watchdog = reactor.callLater(next_timeout, self.retrySendData,
                                                      bytes, next_timeout_ind)
            self.sendData(bytes)

    def sendData(self, bytes):
        self.transport.write(bytes)

    def readFailed(self, fail):
        log.err(fail)
        self.transport.write(ERRORDatagram.from_code(ERR_NOT_DEFINED, "Read failed").to_wire())
        self.transport.stopListening()

class LocalOriginReadSession(ReadSession):

    def __init__(self, remote, reader, handshake_timeout_watchdog):
        self._handshake_timeout_watchdog = handshake_timeout_watchdog
        ReadSession.__init__(self, remote, reader)

    def nextBlock(self):
        if self._handshake_timeout_watchdog.active():
            self._handshake_timeout_watchdog.cancel()
        ReadSession.nextBlock(self)

class RemoteOriginReadSession(ReadSession):

    def startProtocol(self):
        ReadSession.startProtocol(self)
        self.nextBlock()
