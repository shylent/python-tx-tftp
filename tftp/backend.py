'''
@author: shylent
'''
from tftp.errors import Unsupported, FileExists, AccessViolation, FileNotFound
from twisted.python.filepath import FilePath, InsecurePath
import shutil
import tempfile


class FilesystemReader(object):

    def __init__(self, file_path):
        self.file_path = file_path
        try:
            self.file_obj = self.file_path.open('r')
        except IOError:
            raise FileNotFound(self.file_path)
        self.eof = False

    def read(self, bytes):
        if self.eof:
            return ''
        data = self.file_obj.read(bytes)
        if not data:
            self.eof = True
            self.file_obj.close()
        return data


class FilesystemWriter(object):

    def __init__(self, file_path):
        if file_path.exists():
            raise FileExists(file_path)
        self.file_path = file_path
        self.destination_file = self.file_path.open('w')
        self.temp_destination = tempfile.TemporaryFile()

    def write(self, data):
        self.temp_destination.write(data)

    def finish(self):
        self.temp_destination.seek(0)
        shutil.copyfileobj(self.temp_destination, self.destination_file)
        self.temp_destination.close()
        self.destination_file.close()

    def cancel(self):
        self.temp_destination.close()
        self.destination_file.close()
        self.file_path.remove()

class FilesystemSynchronousBackend(object):

    def __init__(self, base_path, can_read=True, can_write=True):
        self.base = FilePath(base_path)
        self.can_read, self.can_write = can_read, can_write

    def get_reader(self, file_name):
        if not self.can_read:
            raise Unsupported("Reading not supported")
        try:
            target_path = self.base.child(file_name)
        except InsecurePath, e:
            raise AccessViolation("Insecure path: %s" % e)
        return FilesystemReader(target_path)

    def get_writer(self, file_name):
        if not self.can_write:
            raise Unsupported("Writing not supported")
        try:
            target_path = self.base.child(file_name)
        except InsecurePath, e:
            raise AccessViolation("Insecure path: %s" % e)
        return FilesystemWriter(target_path)
