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
 - Tests for everything, besides the "outermost" dispatcher protocol
 - Docstrings

##Plans
 - Even more docstrings
 - A convenient interface for sending/receiving files, turn it into a twistd plugin.
 - Support for option negotiation.
 - Multicast.
