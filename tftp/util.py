'''
@author: shylent
'''
from functools import wraps
from itertools import tee
from twisted.internet import reactor
from twisted.internet.defer import CancelledError, maybeDeferred, succeed
from twisted.internet.task import deferLater


__all__ = ['CANCELLED', 'deferred', 'timedCaller']


# Token used by L{timedCaller} to denote that it was cancelled instead of
# finishing naturally. This is not an error condition, and may not be of
# interest during normal use, but is helpful when testing.
CANCELLED = "CANCELLED"


def timedCaller(timings, call, last, clock=reactor):
    """Call C{call} or C{last} according to C{timings}.

    The given C{timings} is an iterable of numbers. Each is a delay in seconds
    that will be taken before making the next call to C{call} or C{last}.

    The call to C{last} will happen after the last delay. If C{timings} is an
    infinite iterable then C{last} will never be called.

    This returns a C{Deferred} which can be cancelled. If the cancellation is
    successful -- i.e. there is something to cancel -- then the result is set
    to L{CANCELLED}. In other words, L{CancelledError} is squashed into a
    non-failure condition.
    """
    timings = iterlast(timings)

    def iterate(_=None):
        for is_last, delay in timings:
            # Return immediately with a deferred call.
            if is_last:
                return deferLater(clock, delay, last)
            else:
                return deferLater(clock, delay, call).addCallback(iterate)
        else:
            # No timings were given.
            return succeed(None)

    def squashCancelled(failure):
        if failure.check(CancelledError) is None:
            return failure
        else:
            return CANCELLED

    return iterate().addErrback(squashCancelled)


def iterlast(iterable):
    """Generate C{(is_last, item)} tuples from C{iterable}.

    On each iteration this peeks ahead to see if the most recent iteration
    will be the last, and returns this information as the C{is_last} element
    of each tuple.
    """
    iterable, peekable = tee(iterable)
    next(peekable)  # Advance in front.
    for item in iterable:
        try:
            next(peekable)
        except StopIteration:
            yield True, item
        else:
            yield False, item


def deferred(func):
    """Decorates a function to ensure that it always returns a `Deferred`.

    This also serves a secondary documentation purpose; functions decorated
    with this are readily identifiable as asynchronous.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        return maybeDeferred(func, *args, **kwargs)
    return wrapper
