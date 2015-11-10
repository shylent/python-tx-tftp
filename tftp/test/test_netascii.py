'''
@author: shylent
'''
from io import BytesIO
from tftp.netascii import (from_netascii, to_netascii, NetasciiReceiverProxy,
    NetasciiSenderProxy)
from twisted.internet.defer import inlineCallbacks
from twisted.trial import unittest
import re
import tftp


class FromNetascii(unittest.TestCase):

    def setUp(self):
        self._orig_nl = tftp.netascii.NL

    def test_lf_newline(self):
        tftp.netascii.NL = b'\x0a'
        self.assertEqual(from_netascii(b'\x0d\x00'), b'\x0d')
        self.assertEqual(from_netascii(b'\x0d\x0a'), b'\x0a')
        self.assertEqual(from_netascii(b'foo\x0d\x0a\x0abar'), b'foo\x0a\x0abar')
        self.assertEqual(from_netascii(b'foo\x0d\x0a\x0abar'), b'foo\x0a\x0abar')
        # freestanding CR should not occur, but handle it anyway
        self.assertEqual(from_netascii(b'foo\x0d\x0a\x0dbar'), b'foo\x0a\x0dbar')

    def test_cr_newline(self):
        tftp.netascii.NL = b'\x0d'
        self.assertEqual(from_netascii(b'\x0d\x00'), b'\x0d')
        self.assertEqual(from_netascii(b'\x0d\x0a'), b'\x0d')
        self.assertEqual(from_netascii(b'foo\x0d\x0a\x0abar'), b'foo\x0d\x0abar')
        self.assertEqual(from_netascii(b'foo\x0d\x0a\x00bar'), b'foo\x0d\x00bar')
        self.assertEqual(from_netascii(b'foo\x0d\x00\x0abar'), b'foo\x0d\x0abar')

    def test_crlf_newline(self):
        tftp.netascii.NL = b'\x0d\x0a'
        self.assertEqual(from_netascii(b'\x0d\x00'), b'\x0d')
        self.assertEqual(from_netascii(b'\x0d\x0a'), b'\x0d\x0a')
        self.assertEqual(from_netascii(b'foo\x0d\x00\x0abar'), b'foo\x0d\x0abar')

    def tearDown(self):
        tftp.netascii.NL = self._orig_nl


class ToNetascii(unittest.TestCase):

    def setUp(self):
        self._orig_nl = tftp.netascii.NL
        self._orig_nl_regex = tftp.netascii.re_to_netascii

    def test_lf_newline(self):
        tftp.netascii.NL = b'\x0a'
        tftp.netascii.re_to_netascii = re.compile(
            tftp.netascii._re_to_netascii.replace(b"NL", tftp.netascii.NL))
        self.assertEqual(to_netascii(b'\x0d'), b'\x0d\x00')
        self.assertEqual(to_netascii(b'\x0a'), b'\x0d\x0a')
        self.assertEqual(to_netascii(b'\x0a\x0d'), b'\x0d\x0a\x0d\x00')
        self.assertEqual(to_netascii(b'\x0d\x0a'), b'\x0d\x00\x0d\x0a')

    def test_cr_newline(self):
        tftp.netascii.NL = b'\x0d'
        tftp.netascii.re_to_netascii = re.compile(
            tftp.netascii._re_to_netascii.replace(b"NL", tftp.netascii.NL))
        self.assertEqual(to_netascii(b'\x0d'), b'\x0d\x0a')
        self.assertEqual(to_netascii(b'\x0a'), b'\x0a')
        self.assertEqual(to_netascii(b'\x0d\x0a'), b'\x0d\x0a\x0a')
        self.assertEqual(to_netascii(b'\x0a\x0d'), b'\x0a\x0d\x0a')

    def test_crlf_newline(self):
        tftp.netascii.NL = b'\x0d\x0a'
        tftp.netascii.re_to_netascii = re.compile(
            tftp.netascii._re_to_netascii.replace(b"NL", tftp.netascii.NL))
        self.assertEqual(to_netascii(b'\x0d\x0a'), b'\x0d\x0a')
        self.assertEqual(to_netascii(b'\x0d'), b'\x0d\x00')
        self.assertEqual(to_netascii(b'\x0d\x0a\x0d'), b'\x0d\x0a\x0d\x00')
        self.assertEqual(to_netascii(b'\x0d\x0d\x0a'), b'\x0d\x00\x0d\x0a')

    def tearDown(self):
        tftp.netascii.NL = self._orig_nl
        tftp.netascii.re_to_netascii = self._orig_nl_regex


class ReceiverProxy(unittest.TestCase):

    test_data = b"""line1
line2
line3
"""
    def setUp(self):
        self.source = BytesIO(to_netascii(self.test_data))
        self.sink = BytesIO()

    @inlineCallbacks
    def test_conversion(self):
        p = NetasciiReceiverProxy(self.sink)
        chunk = self.source.read(2)
        while chunk:
            yield p.write(chunk)
            chunk = self.source.read(2)
        self.sink.seek(0) # !!!
        self.assertEqual(self.sink.read(), self.test_data)

    @inlineCallbacks
    def test_conversion_byte_by_byte(self):
        p = NetasciiReceiverProxy(self.sink)
        chunk = self.source.read(1)
        while chunk:
            yield p.write(chunk)
            chunk = self.source.read(1)
        self.sink.seek(0) # !!!
        self.assertEqual(self.sink.read(), self.test_data)

    @inlineCallbacks
    def test_conversion_normal(self):
        p = NetasciiReceiverProxy(self.sink)
        chunk = self.source.read(1)
        while chunk:
            yield p.write(chunk)
            chunk = self.source.read(5)
        self.sink.seek(0) # !!!
        self.assertEqual(self.sink.read(), self.test_data)


class SenderProxy(unittest.TestCase):

    test_data = b"""line1
line2
line3
"""
    def setUp(self):
        self.source = BytesIO(self.test_data)
        self.sink = BytesIO()

    @inlineCallbacks
    def test_conversion_normal(self):
        p = NetasciiSenderProxy(self.source)
        chunk = yield p.read(5)
        self.assertEqual(len(chunk), 5)
        self.sink.write(chunk)
        last_chunk = False
        while chunk:
            chunk = yield p.read(5)
            # If a terminating chunk (len < blocknum) was already sent, there should
            # be no more data (means, we can only yield empty lines from now on)
            if last_chunk and chunk:
                print("LEN: %s" % len(chunk))
                self.fail("Last chunk (with len < blocksize) was already yielded, "
                          "but there is more data.")
            if len(chunk) < 5:
                last_chunk = True
            self.sink.write(chunk)
        self.sink.seek(0)
        self.assertEqual(self.sink.read(), to_netascii(self.test_data))

    @inlineCallbacks
    def test_conversion_byte_by_byte(self):
        p = NetasciiSenderProxy(self.source)
        chunk = yield p.read(1)
        self.assertEqual(len(chunk), 1)
        self.sink.write(chunk)
        last_chunk = False
        while chunk:
            chunk = yield p.read(1)
            # If a terminating chunk (len < blocknum) was already sent, there should
            # be no more data (means, we can only yield empty lines from now on)
            if last_chunk and chunk:
                print("LEN: %s" % len(chunk))
                self.fail("Last chunk (with len < blocksize) was already yielded, "
                          "but there is more data.")
            if len(chunk) < 1:
                last_chunk = True
            self.sink.write(chunk)
        self.sink.seek(0)
        self.assertEqual(self.sink.read(), to_netascii(self.test_data))

    @inlineCallbacks
    def test_conversion(self):
        p = NetasciiSenderProxy(self.source)
        chunk = yield p.read(2)
        self.assertEqual(len(chunk), 2)
        self.sink.write(chunk)
        last_chunk = False
        while chunk:
            chunk = yield p.read(2)
            # If a terminating chunk (len < blocknum) was already sent, there should
            # be no more data (means, we can only yield empty lines from now on)
            if last_chunk and chunk:
                print("LEN: %s" % len(chunk))
                self.fail("Last chunk (with len < blocksize) was already yielded, "
                          "but there is more data.")
            if len(chunk) < 2:
                last_chunk = True
            self.sink.write(chunk)
        self.sink.seek(0)
        self.assertEqual(self.sink.read(), to_netascii(self.test_data))
