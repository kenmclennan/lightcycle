"""Period: an inclusive date range for the worklog (a value object)."""
import datetime
from dataclasses import dataclass


@dataclass(frozen=True)
class Period:
    start: datetime.date
    end: datetime.date

    @classmethod
    def resolve(cls, args, today) -> "Period":
        """Resolve positional date args to an inclusive range. Each arg is 'today',
        'yesterday', or 'YYYY-MM-DD'. No args -> today for both bounds. today is passed
        in (the domain reads no ambient clock)."""
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
