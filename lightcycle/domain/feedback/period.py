import datetime
from dataclasses import dataclass


@dataclass(frozen=True)
class Period:
    start: datetime.date
    end: datetime.date

    @classmethod
    def resolve(cls, args, today) -> "Period":
        def _parse(arg):
            if arg == "today":
                return today
            if arg == "yesterday":
                return today - datetime.timedelta(days=1)
            return datetime.date.fromisoformat(arg)

        if not args:
            return cls(today, today)
        if len(args) == 1:
            d = _parse(args[0])
            return cls(d, d)
        return cls(_parse(args[0]), _parse(args[1]))

    def contains(self, day) -> bool:
        return self.start <= day <= self.end
