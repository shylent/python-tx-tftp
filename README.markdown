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
 - An actual TFTP server.
 - Fully-tested internals (wire protocol, conversions, backend).

##Plans
 - <del>Docstrings</del>More docstrings.
 - Tests for the actual protocol.
 - I will factor out the functionality, that is common to the client and the server
 and add a convenient interface for sending/receiving files.
 - Support for option negotiation.
 - Multicast.
