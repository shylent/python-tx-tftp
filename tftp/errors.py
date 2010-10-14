'''
@author: shylent
'''

class TFTPError(Exception):
    pass

class WireProtocolError(TFTPError):
    pass


class InvalidOpcodeError(WireProtocolError):

    def __init__(self, opcode):

        super(InvalidOpcodeError, self).__init__("Invalid opcode: %s" % opcode)

class PayloadDecodeError(WireProtocolError):
    pass

class InvalidErrorcodeError(PayloadDecodeError):
    
    def __init__(self, errorcode):
        self.errorcode = errorcode
        super(InvalidErrorcodeError, self).__init__("Unknown error code: %s" % errorcode)
        
class BackendError(TFTPError):
    pass

class Unsupported(BackendError):
    pass

class AccessViolation(BackendError):
    pass

class FileNotFound(BackendError):

    def __init__(self, file_path):
        self.file_path = file_path
    
    def __str__(self):
        return "File not found: %s" % self.file_path


class FileExists(BackendError):
    
    def __init__(self, file_path):
        self.file_path = file_path
    
    def __str__(self):
        return "File already exists: %s" % self.file_path
