'''
@author: shylent
'''

class TFTPError(Exception):
    pass

class BinaryProtocolError(TFTPError):
    pass


class InvalidOpcodeError(BinaryProtocolError):
    
    def __init__(self, opcode):
        super(InvalidOpcodeError, self).__init__("Invalid opcode: %s" % opcode)

class PayloadDecodeError(BinaryProtocolError):
    pass

class InvalidErrorcodeError(PayloadDecodeError):
    
    def __init__(self, errorcode):
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
