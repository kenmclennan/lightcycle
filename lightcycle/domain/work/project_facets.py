import re

_FACET_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def parse_facets(text):
    if text == "":
        return ()
    facets = []
    for token in text.split(","):
        if not _FACET_RE.match(token):
            raise ValueError(
                "invalid facet %r - a facet is a lowercase kebab-case name such as "
                "'kotlin' or 'spring-boot'" % token
            )
        if token not in facets:
            facets.append(token)
    return tuple(facets)


def format_facets(facets):
    return ",".join(facets)


def unformat_facets(text):
    if not text:
        return ()
    return tuple(text.split(","))
