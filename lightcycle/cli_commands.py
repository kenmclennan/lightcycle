import argparse
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class Arg:
    name: str
    action: Optional[str] = None
    nargs: object = None
    type: Optional[type] = None
    default: object = None
    choices: Optional[Tuple] = None
    help: Optional[str] = None
    metavar: Optional[str] = None


@dataclass(frozen=True)
class MutexGroup:
    args: Tuple[Arg, ...]
    required: bool = False


@dataclass(frozen=True)
class CommandSpec:
    prog: str
    args: Tuple = ()
    subparsers: Optional[dict] = None


def _kwargs(arg):
    kwargs = {}
    for field in ("action", "nargs", "type", "default", "choices", "help", "metavar"):
        value = getattr(arg, field)
        if value is not None:
            kwargs[field] = value
    return kwargs


def _populate(parser, args):
    for item in args:
        if isinstance(item, MutexGroup):
            group = parser.add_mutually_exclusive_group(required=item.required)
            for a in item.args:
                group.add_argument(a.name, **_kwargs(a))
        else:
            parser.add_argument(item.name, **_kwargs(item))


def build_parser(spec):
    parser = argparse.ArgumentParser(prog=spec.prog)
    _populate(parser, spec.args)
    if spec.subparsers:
        sub = parser.add_subparsers(dest="sub")
        for name, subspec in spec.subparsers.items():
            _populate(sub.add_parser(name), subspec.args)
    return parser


def _flags_of(args):
    out = set()
    for item in args:
        if isinstance(item, MutexGroup):
            out |= _flags_of(item.args)
        elif item.name.startswith("--"):
            out.add(item.name[2:])
    return out


COMMANDS = {
    "version": CommandSpec(prog="lc version"),
    "upgrade": CommandSpec(prog="lc upgrade", args=(
        Arg("--check", action="store_true"),
    )),
    "workflow": CommandSpec(prog="lc workflow", subparsers={
        "add": CommandSpec(prog="lc workflow add", args=(
            Arg("url"), Arg("--ref"), Arg("--name"),
        )),
        "init": CommandSpec(prog="lc workflow init", args=(
            Arg("name"),
        )),
        "upgrade": CommandSpec(prog="lc workflow upgrade", args=(
            Arg("origin", nargs="?"),
        )),
        "list": CommandSpec(prog="lc workflow list"),
        "check": CommandSpec(prog="lc workflow check", args=(
            Arg("workflow"), Arg("--json", action="store_true"),
        )),
        "describe": CommandSpec(prog="lc workflow describe", args=(
            Arg("workflow"), Arg("--mermaid", action="store_true"),
        )),
        "simulate": CommandSpec(prog="lc workflow simulate", args=(
            Arg("workflow"),
        )),
        "rm": CommandSpec(prog="lc workflow rm", args=(
            Arg("origin"),
        )),
    }),
    "show": CommandSpec(prog="lc show", args=(
        Arg("id"),
    )),
    "peek": CommandSpec(prog="lc peek", args=(
        Arg("id"), Arg("stage"),
    )),
    "claim": CommandSpec(prog="lc claim", args=(
        Arg("role"),
    )),
    "spawn": CommandSpec(prog="lc spawn", args=(
        Arg("role"),
    )),
    "ps": CommandSpec(prog="lc ps", args=(
        Arg("--all", action="store_true"), Arg("--json", action="store_true"),
    )),
    "logs": CommandSpec(prog="lc logs", args=(
        Arg("target"), Arg("-f", action="store_true"),
    )),
    "advance": CommandSpec(prog="lc advance", args=(
        Arg("id"), Arg("outcome"),
    )),
    "ready-roles": CommandSpec(prog="lc ready-roles"),
    "specs-dir": CommandSpec(prog="lc specs-dir", args=(
        Arg("--check", action="store_true"),
    )),
    "done": CommandSpec(prog="lc done", args=(
        Arg("id"), Arg("outcome"),
        Arg("--note", nargs="+", help="a note to forward to the next step; unquoted multi-word is fine"),
        Arg("--disposition", choices=("completed", "aborted")),
    )),
    "trace": CommandSpec(prog="lc trace", args=(
        Arg("item"), Arg("--json", action="store_true"),
    )),
    "sweep": CommandSpec(prog="lc sweep"),
    "restore": CommandSpec(prog="lc restore", args=(
        Arg("snapshot", nargs="?"), Arg("--force", action="store_true"),
        Arg("--list", action="store_true"),
    )),
    "doctor": CommandSpec(prog="lc doctor", args=(
        Arg("--json", action="store_true"),
    )),
    "backfill-usage": CommandSpec(prog="lc backfill-usage", args=(
        Arg("--repair", action="store_true"),
    )),
    "inbox": CommandSpec(prog="lc inbox", args=(
        Arg("n", nargs="?", type=int),
    )),
    "backlog": CommandSpec(prog="lc backlog", args=(
        Arg("n", nargs="?", type=int), Arg("--project"),
    )),
    "search": CommandSpec(prog="lc search", args=(
        Arg("text"),
    )),
    "active": CommandSpec(prog="lc active"),
    "queue": CommandSpec(prog="lc queue", args=(
        Arg("n", nargs="?", type=int, default=10),
    )),
    "tui": CommandSpec(prog="lc tui"),
    "new": CommandSpec(prog="lc new", args=(
        Arg("type"), Arg("title"),
        Arg("--parent", help="owning item, for 'lc new step'"),
        Arg("--workflow"), Arg("--project"), Arg("--repo"), Arg("--description"),
        Arg("--note", nargs="+", help="an observation for whoever picks the step up"),
        Arg("--backlog", action="append"), Arg("--step"),
    )),
    "set": CommandSpec(prog="lc set", args=(
        *(Arg("--%s" % opt) for opt in (
            "title", "description", "project", "workflow", "state", "label",
            "needs", "reason", "tried", "step", "notes",
        )),
        Arg("--backlog", action="append"), Arg("--depends", action="append"),
        Arg("--unset", action="append"), Arg("id"),
    )),
    "attach": CommandSpec(prog="lc attach", args=(
        Arg("id"), Arg("type"),
        MutexGroup(required=True, args=(Arg("value", nargs="?"), Arg("--file"))),
        Arg("--label"), Arg("--replace", action="store_true"),
        Arg("--internal", action="store_true"), Arg("--kind"),
    )),
    "dep": CommandSpec(prog="lc dep", args=(
        Arg("id"),
        MutexGroup(required=True, args=(Arg("--needs"), Arg("--remove"))),
    )),
    "rm": CommandSpec(prog="lc rm", args=(
        Arg("id"), Arg("--force", action="store_true"),
    )),
    "start": CommandSpec(prog="lc start", args=(
        Arg("--once", action="store_true"), Arg("--detach", action="store_true"),
    )),
    "init": CommandSpec(prog="lc init"),
    "project": CommandSpec(prog="lc project", subparsers={
        "add": CommandSpec(prog="lc project add", args=(
            Arg("identity"), Arg("--shortcode"), Arg("--path"),
        )),
        "list": CommandSpec(prog="lc project list"),
        "rm": CommandSpec(prog="lc project rm", args=(
            Arg("identity"),
        )),
        "scan": CommandSpec(prog="lc project scan", args=(
            Arg("dir", nargs="?", default="."), Arg("--json", action="store_true"),
        )),
    }),
    "config": CommandSpec(prog="lc config", args=(
        Arg("--edit", action="store_true"),
    )),
    "status": CommandSpec(prog="lc status", args=(
        Arg("--json", action="store_true"),
    )),
    "worklog": CommandSpec(prog="lc worklog", args=(
        Arg("start", nargs="?"), Arg("end", nargs="?"),
    )),
    "retro": CommandSpec(prog="lc retro", args=(
        Arg("id", nargs="?", default=None, help="item id"),
        Arg("--since", metavar="YYYY-MM-DD", help="aggregate steps closed on/after date"),
        Arg("--last", type=int, metavar="N", help="aggregate last N closed items"),
        Arg("--project", metavar="REPO", help="aggregate a project's closed unretroed items"),
        Arg("--pending", action="store_true",
            help="aggregate all closed unretroed items that carry feedback"),
    )),
}


def flags_by_verb(commands=COMMANDS):
    result = {}
    for verb, spec in commands.items():
        flags = _flags_of(spec.args)
        if spec.subparsers:
            for subspec in spec.subparsers.values():
                flags |= _flags_of(subspec.args)
        result[verb] = flags
    return result
