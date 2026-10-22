import functools


class PoolCrash(BaseException):
    pass


class CrashPoint:
    def __init__(self, target, method, nth=1, when="after", match=None):
        if when not in ("before", "after"):
            raise ValueError("when must be 'before' or 'after', got %r" % when)
        self._target = target
        self._method = method
        self._nth = nth
        self._when = when
        self._match = match
        self._own = method in vars(target)
        self._original = getattr(target, method)
        self.calls = 0
        self.fired = False
        self._armed = True
        setattr(target, method, self._wrapper())

    def _wrapper(self):
        original = self._original

        @functools.wraps(original)
        def wrapper(*args, **kwargs):
            counted = self._armed and not self.fired and (
                self._match is None or self._match(*args, **kwargs))
            if counted:
                self.calls += 1
            fire = counted and self.calls == self._nth
            if fire and self._when == "before":
                self.fired = True
                raise PoolCrash("%s before call %d" % (self._method, self._nth))
            result = original(*args, **kwargs)
            if fire:
                self.fired = True
                raise PoolCrash("%s after call %d" % (self._method, self._nth))
            return result

        return wrapper

    def disarm(self):
        self._armed = False
        if self._own:
            setattr(self._target, self._method, self._original)
        elif self._method in vars(self._target):
            delattr(self._target, self._method)


def crash_on(target, method, nth=1, when="after", match=None):
    return CrashPoint(target, method, nth=nth, when=when, match=match)
