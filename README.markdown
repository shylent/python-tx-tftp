python-tx-tftp
==
A Twisted-based TFTP implementation

##What's already there
 
 - [RFC1350](http://tools.ietf.org/html/rfc1350) (base TFTP specification) support.
 - Asynchronous backend support. It is not assumed, that filesystem access is 
 'fast enough'. While current backends use synchronous reads/writes, the code does
 not rely on this anywhere, so plugging in an asynchronous backend should not be
 a problem.
 - netascii transfer mode.
 - Option negotiation support. 'blksize' and 'timeout' options are supported.
 - An actual TFTP server.
 - Plugin for twistd.
 - Tests
 - Docstrings

##Plans
 - Client-specific commandline interface.
 - Code cleanup.
 - Multicast support (possibly).
