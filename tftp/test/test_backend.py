'''
@author: shylent
'''
from tftp.backend import (FilesystemSynchronousBackend, FilesystemReader,
    FilesystemWriter, IReader, IWriter)
from tftp.errors import Unsupported, AccessViolation, FileNotFound, FileExists
from twisted.python.filepath import FilePath
from twisted.trial import unittest
import os.path
import shutil
import tempfile


class BackendSelection(unittest.TestCase):
    test_data = """line1
line2
line3
"""


    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.existing_file_name = os.path.join(self.temp_dir, 'foo')
        with open(self.existing_file_name, 'w') as f:
            f.write(self.test_data)

    def test_read_supported_by_default(self):
        b = FilesystemSynchronousBackend(self.temp_dir)
        return b.get_reader('foo').addCallback(IReader.providedBy)

    def test_write_supported_by_default(self):
        b = FilesystemSynchronousBackend(self.temp_dir)
        return b.get_writer('bar').addCallback(IWriter.providedBy)

    def test_read_unsupported(self):
        b = FilesystemSynchronousBackend(self.temp_dir, can_read=False)
        return self.assertFailure(b.get_reader('foo'), Unsupported)

    def test_write_unsupported(self):
        b = FilesystemSynchronousBackend(self.temp_dir, can_write=False)
        return self.assertFailure(b.get_writer('bar'), Unsupported)

    def test_insecure_reader(self):
        b = FilesystemSynchronousBackend(self.temp_dir)
        return self.assertFailure(
            b.get_reader('../foo'), AccessViolation)

    def test_insecure_writer(self):
        b = FilesystemSynchronousBackend(self.temp_dir)
        return self.assertFailure(
            b.get_writer('../foo'), AccessViolation)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)


class Reader(unittest.TestCase):
    test_data = """line1
line2
line3
"""

    def setUp(self):
        self.temp_dir = FilePath(tempfile.mkdtemp())
        self.existing_file_name = self.temp_dir.child('foo')
        with self.existing_file_name.open('w') as f:
            f.write(self.test_data)

    def test_file_not_found(self):
        self.assertRaises(FileNotFound, FilesystemReader, self.temp_dir.child('bar'))

    def test_read_existing_file(self):
        r = FilesystemReader(self.temp_dir.child('foo'))
        data = r.read(3)
        ostring = data
        while data:
            data = r.read(3)
            ostring += data
        self.assertEqual(r.read(3), '')
        self.assertEqual(r.read(5), '')
        self.assertEqual(r.read(7), '')
        self.failUnless(r.file_obj.closed,
                        "The file has been exhausted and should be in the closed state")
        self.assertEqual(ostring, self.test_data)

    def test_size(self):
        r = FilesystemReader(self.temp_dir.child('foo'))
        self.assertEqual(len(self.test_data), r.size)

    def test_size_when_reader_finished(self):
        r = FilesystemReader(self.temp_dir.child('foo'))
        r.finish()
        self.assertIsNone(r.size)

    def test_size_when_file_removed(self):
        # FilesystemReader.size uses fstat() to discover the file's size, so
        # the absence of the file does not matter.
        r = FilesystemReader(self.temp_dir.child('foo'))
        self.existing_file_name.remove()
        self.assertEqual(len(self.test_data), r.size)

    def test_cancel(self):
        r = FilesystemReader(self.temp_dir.child('foo'))
        r.read(3)
        r.finish()
        self.failUnless(r.file_obj.closed,

            "The session has been finished, so the file object should be in the closed state")
        r.finish()

    def tearDown(self):
        self.temp_dir.remove()


class Writer(unittest.TestCase):
    test_data = """line1
line2
line3
"""

    def setUp(self):
        self.temp_dir = FilePath(tempfile.mkdtemp())
        self.existing_file_name = self.temp_dir.child('foo')
        with self.existing_file_name.open('w') as f:
            f.write(self.test_data)

    def test_write_existing_file(self):
        self.assertRaises(FileExists, FilesystemWriter, self.temp_dir.child('foo'))

    def test_finished_write(self):
        w = FilesystemWriter(self.temp_dir.child('bar'))
        w.write(self.test_data)
        w.finish()
        with self.temp_dir.child('bar').open() as f:
            self.assertEqual(f.read(), self.test_data)

    def test_cancelled_write(self):
        w = FilesystemWriter(self.temp_dir.child('bar'))
        w.write(self.test_data)
        w.cancel()
        self.failIf(self.temp_dir.child('bar').exists(),
                    "If a write is cancelled, the file should not be left behind")

    def tearDown(self):
        self.temp_dir.remove()
