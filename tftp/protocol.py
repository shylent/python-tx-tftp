'''
@author: shylent
'''
from tftp.datagram import (TFTPDatagramFactory, split_opcode, OP_WRQ,
    ERRORDatagram, ERR_NOT_DEFINED, ERR_ACCESS_VIOLATION, ERR_FILE_EXISTS,
    ERR_ILLEGAL_OP, OP_RRQ, ERR_FILE_NOT_FOUND)
from tftp.errors import (FileExists, Unsupported, AccessViolation, BackendError,
    FileNotFound)
from tftp.netascii import NetasciiReceiverProxy
from tftp.session import WriteSession, ReadSession
from twisted.internet import reactor
from twisted.internet.protocol import DatagramProtocol
from twisted.python import log
import random


class TFTP(DatagramProtocol):

    def __init__(self, backend):
        self.backend = backend

    def _free_port(self):
        return random.randint(49152, 65535)

    def startProtocol(self):
        addr = self.transport.getHost()
        log.msg("TFTP Listener started at %s:%s" % (addr.host, addr.port))

    def datagramReceived(self, datagram, addr):
        datagram = TFTPDatagramFactory(*split_opcode(datagram))
        log.msg("Datagram received from %s: %s" % (addr, datagram))
        if datagram.opcode == OP_WRQ:
            try:
                writer = self.backend.get_writer(datagram.filename)
            except Unsupported:
                self.transport.write(ERRORDatagram.from_code(ERR_NOT_DEFINED,
                                        "Writing not supported").to_wire(), addr)
            except AccessViolation:
                self.transport.write(ERRORDatagram.from_code(ERR_ACCESS_VIOLATION).to_wire(), addr)
            except FileExists:
                self.transport.write(ERRORDatagram.from_code(ERR_FILE_EXISTS).to_wire(), addr)
            except BackendError, e:
                self.transport.write(ERRORDatagram.from_code(ERR_NOT_DEFINED, str(e)).to_wire(), addr)
            else:
                if datagram.mode.lower() == 'netascii':
                    writer = NetasciiReceiverProxy(writer)
                elif datagram.mode.lower() != 'octet':
                    self.transport.write(ERRORDatagram.from_code(ERR_ILLEGAL_OP,
                                        "Unknown transfer mode %s, - expected "
                                        "'netascii' or 'octet' (case-insensitive)").to_wire(), addr)
                session = WriteSession(addr, writer)
                my_port = self._free_port()
                reactor.listenUDP(my_port, session)
        elif datagram.opcode == OP_RRQ:
            try:
                reader = self.backend.get_reader(datagram.filename)
            except Unsupported:
                self.transport.write(ERRORDatagram.from_code(ERR_NOT_DEFINED,
                                                   "Writing not supported").to_wire(), addr)
            except AccessViolation:
                self.transport.write(ERRORDatagram.from_code(ERR_ACCESS_VIOLATION).to_wire(), addr)
            except FileNotFound:
                self.transport.write(ERRORDatagram.from_code(ERR_FILE_NOT_FOUND).to_wire(), addr)
            except BackendError, e:
                self.transport.write(ERRORDatagram.from_code(ERR_NOT_DEFINED, str(e)).to_wire(), addr)
            else:
                if datagram.mode.lower() == 'netascii':
                    reader = NetasciiReceiverProxy(reader)
                elif datagram.mode.lower() != 'octet':
                    self.transport.write(ERRORDatagram.from_code(ERR_ILLEGAL_OP,
                                        "Unknown transfer mode %s, - expected "
                                        "'netascii' or 'octet' (case-insensitive)").to_wire(), addr)
                session = ReadSession(addr, reader)
                my_port = self._free_port()
                reactor.listenUDP(my_port, session)
