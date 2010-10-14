'''
@author: shylent
'''
# So basically, the idea is that in netascii a *newline* (whatever that is 
# on the current platform) is represented by a CR+LF sequence and a single CR
# is represented by CR+NUL.

from twisted.internet.defer import maybeDeferred, succeed
import os
import re

__all__ = ['NetasciiSenderProxy', 'NetasciiReceiverProxy',
           'to_netascii', 'from_netascii']

CR = '\x0d'
LF = '\x0a'
CRLF = CR + LF
NUL = '\x00'
CRNUL = CR + NUL

NL = os.linesep


re_from_netascii = re.compile('(\x0d\x0a|\x0d\x00)')

def _convert_from_netascii(match_obj):
    if match_obj.group(0) == CRLF:
        return NL
    elif match_obj.group(0) == CRNUL:
        return CR

def from_netascii(data):
    return re_from_netascii.sub(_convert_from_netascii, data)

# So that I can easily switch the NL around in tests
_re_to_netascii = '(%s|\x0d)'
re_to_netascii = re.compile(_re_to_netascii % NL)

def _convert_to_netascii(match_obj):
    if match_obj.group(0) == NL:
        return CRLF
    elif match_obj.group(0) == CR:
        return CRNUL

def to_netascii(data):
    return re_to_netascii.sub(_convert_to_netascii, data)

class NetasciiReceiverProxy(object):

    def __init__(self, writer):
        self.writer = writer
        self._carry_cr = False

    def write(self, data):
        if self._carry_cr:
            data = CR + data
        data = from_netascii(data)
        if data.endswith(CR):
            self._carry_cr = True
            return maybeDeferred(self.writer.write, data[:-1])
        else:
            self._carry_cr = False
            return maybeDeferred(self.writer.write, data)

    def __getattr__(self, name):
        return getattr(self.writer, name)


class NetasciiSenderProxy(object):

    def __init__(self, reader):
        self.reader = reader
        self.buffer = ''

    def read(self, bytes):
        need_bytes = bytes - len(self.buffer)
        if need_bytes <= 0:
            data, self.buffer = self.buffer[:bytes], self.buffer[bytes:]
            return succeed(data)
        d = maybeDeferred(self.reader.read, need_bytes)
        d.addCallback(self.gotDataFromReader, bytes)
        return d

    def gotDataFromReader(self, data, bytes):
        data = self.buffer + to_netascii(data)
        data, self.buffer = data[:bytes], data[bytes:]
        return data

    def __getattr__(self, name):
        return getattr(self.reader, name)
