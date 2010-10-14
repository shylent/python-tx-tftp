'''
@author: shylent
'''
from tftp.errors import (WireProtocolError, InvalidOpcodeError, 
    PayloadDecodeError, InvalidErrorcodeError)
import struct

OP_RRQ = 1
OP_WRQ = 2
OP_DATA = 3
OP_ACK = 4
OP_ERROR = 5

ERR_NOT_DEFINED = 0
ERR_FILE_NOT_FOUND = 1
ERR_ACCESS_VIOLATION = 2
ERR_DISK_FULL = 3
ERR_ILLEGAL_OP = 4
ERR_TID_UNKNOWN = 5
ERR_FILE_EXISTS = 6
ERR_NO_SUCH_USER = 7

errors = {
    ERR_NOT_DEFINED :       "",
    ERR_FILE_NOT_FOUND  :   "File not found",
    ERR_ACCESS_VIOLATION :  "Access violation",
    ERR_DISK_FULL :         "Disk full or allocation exceeded",
    ERR_ILLEGAL_OP :        "Illegal TFTP operation",
    ERR_TID_UNKNOWN :       "Unknown transfer ID",
    ERR_FILE_EXISTS :       "File already exists",
    ERR_NO_SUCH_USER :      "No such user"

}

def split_opcode(datagram):
    try:
        return struct.unpack("!H", datagram[:2])[0], datagram[2:]
    except struct.error:
        raise WireProtocolError()

class TFTPDatagram(object):
    
    
    @classmethod
    def from_wire(cls):
        raise NotImplementedError("Subclasses must override this")

    def to_wire(self):
        raise NotImplementedError("Subclasses must override this")
    
class RQDatagram(TFTPDatagram):
    
    @classmethod
    def from_wire(cls, payload):
        parts = payload.split('\x00')
        try:
            return cls(parts[0], parts[1])
        except IndexError:
            raise PayloadDecodeError()

    def __init__(self, filename, mode):
        self.filename = filename
        self.mode = mode.lower()
        
    def __repr__(self):
        return "<%s(filename=%s, mode=%s)>" % (self.__class__.__name__,
                                               self.filename, self.mode)
    
    def to_wire(self):
        return ''.join((struct.pack("!H", self.opcode),
                        self.filename, '\x00', self.mode, '\x00'))

class RRQDatagram(RQDatagram):
    opcode = OP_RRQ

class WRQDatagram(RQDatagram):
    opcode = OP_WRQ

class DATADatagram(TFTPDatagram):
    opcode = OP_DATA
    
    @classmethod
    def from_wire(cls, payload):
        try:
            blocknum, data = struct.unpack('!H', payload[:2])[0], payload[2:]
        except struct.error:
            raise PayloadDecodeError()
        return cls(blocknum, data)

    def __init__(self, blocknum, data):
        self.blocknum = blocknum
        self.data = data
    
    def __repr__(self):
        return "<%s(blocknum=%s, %s bytes of data)>" % (self.__class__.__name__,
                                                        self.blocknum, len(self.data))
        
    def to_wire(self):
        return ''.join((struct.pack('!HH', self.opcode, self.blocknum), self.data))

class ACKDatagram(TFTPDatagram):
    opcode = OP_ACK
    
    @classmethod
    def from_wire(cls, data):
        try:
            blocknum = struct.unpack('!H', data)[0]
        except struct.error:
            raise PayloadDecodeError()
        return cls(blocknum)
    
    def __init__(self, blocknum):
        self.blocknum = blocknum
    
    def __repr__(self):
        return "<%s(blocknum=%s)>" % (self.__class__.__name__, self.blocknum)
    
    def to_wire(self):
        return struct.pack('!HH', self.opcode, self.blocknum)

class ERRORDatagram(TFTPDatagram):
    opcode = OP_ERROR
    
    @classmethod
    def from_wire(cls, data):
        try:
            errorcode = struct.unpack('!H', data[:2])[0]
        except struct.error:
            raise PayloadDecodeError()
        if not errorcode in errors:
            raise InvalidErrorcodeError(errorcode)
        errmsg = data[2:].split('\x00')[0]
        if not errmsg:
            errmsg = errors[errorcode]
        return cls(errorcode, errmsg)
    
    @classmethod
    def from_code(cls, errorcode, errmsg=None):
        if not errorcode in errors:
            raise InvalidErrorcodeError(errorcode)
        if errmsg is None:
            errmsg = errors[errorcode]
        return cls(errorcode, errmsg)
        
        
    def __init__(self, errorcode, errmsg):
        self.errorcode = errorcode
        self.errmsg = errmsg
        
    def to_wire(self):
        return ''.join((struct.pack('!HH', self.opcode, self.errorcode),
                        self.errmsg, '\x00'))

class _TFTPDatagramFactory(object):
    _dgram_classes = {
        OP_RRQ: RRQDatagram,
        OP_WRQ : WRQDatagram,
        OP_DATA : DATADatagram,
        OP_ACK : ACKDatagram,
        OP_ERROR : ERRORDatagram
    }
    def __call__(self, opcode, payload):
        try:
            datagram_class = self._dgram_classes[opcode]
        except KeyError:
            raise InvalidOpcodeError(opcode) 
        return datagram_class.from_wire(payload)
TFTPDatagramFactory = _TFTPDatagramFactory()
