import json
import sys
import time

from lightcycle.cli_commands import COMMANDS, build_parser

from lightcycle.application.errors import UseCaseError
from lightcycle.application.inspect import DoctorInput, DoctorUseCase
from lightcycle.application.workflows.add import AddWorkflowSourceUseCase
from lightcycle.application.setup import (
    AddProjectInput,
    AddProjectUseCase,
    SetProjectUseCase,
    InitGridUseCase,
    ListProjectsUseCase,
    RemoveProjectUseCase,
    RestoreInput,
    RestoreStoreUseCase,
    ScanProjectsUseCase,
)
from lightcycle.config import RESTART_REQUIRED_KEYS, ConfigError
from lightcycle.ports.workflow_source import WorkflowSourceError


from lightcycle.commands.context import container



def cmd_restore(argv):
    a = build_parser(COMMANDS["restore"]).parse_args(argv)
    if a.list:
        now = time.time()
        for snap in container().backup.list_snapshots():
            print("%s  age=%ds" % (snap.name, int(now - snap.taken_at)))
        return 0
    try:
        resp = RestoreStoreUseCase(
            container().lock, container().store, container().backup, container().config
        ).execute(RestoreInput(snapshot=a.snapshot, force=a.force))
    except UseCaseError as e:
        sys.stderr.write("%s\n" % e)
        return 1
    print("restored %s (age %ds)" % (resp.snapshot, int(time.time() - resp.taken_at)))
    return 0


def cmd_doctor(argv):
    a = build_parser(COMMANDS["doctor"]).parse_args(argv)
    report = DoctorUseCase(
        container().store, container().workflow_source, container().config, container().workflow_bundle,
        container().fs, container().machine, container().worktrees(),
        container().git, container().guidance_sync_status,
        container().config_reload_status, container().lock, container().github_budget(),
    ).execute(DoctorInput())
    if a.json:
        print(json.dumps(
            {cat: [p.as_dict() for p in probs] for cat, probs in report.problems.items()},
            indent=2,
        ))
        return 0 if report.healthy() else 1
    for cat, probs in report.problems.items():
        if not probs:
            print("%s: %s" % (cat, report.notes.get(cat, "ok")))
            continue
        print("%s:" % cat)
        for p in probs:
            suffix = " (%s)" % p.node_id if p.node_id else ""
            print("  %s%s" % (p.message, suffix))
            if p.fix:
                print("    fix: %s" % p.fix)
    print("healthy" if report.healthy() else "unhealthy")
    return 0 if report.healthy() else 1


def cmd_init(argv):
    a = build_parser(COMMANDS["init"]).parse_args(argv)
    c = container()
    try:
        r = InitGridUseCase(c.store, c.fs, c.config, c.git, c.github).execute(a.guidance_path)
    except UseCaseError as e:
        sys.stderr.write("lc init: %s\n" % e)
        return 1
    print("lightcycle store already initialised" if r.existed else "lightcycle store initialised")
    print("config %s at %s" % ("created" if r.created else "already exists", r.config_path))
    print("guidance repo %s at %s" % (r.guidance_outcome, r.guidance_path))
    for line in r.remote_updates:
        print(line)
    if r.trusted_authors_seeded:
        print("trusted-authors set to %s (the gh identity); edit the config to add others"
              % r.trusted_authors_seeded)
    elif r.trusted_authors_unset_reason:
        print(
            "trusted-authors is unset (%s): the pool will not act on PR comments until it is set"
            % r.trusted_authors_unset_reason
        )
    _init_pull_default_origin()
    if r.guidance_refusal:
        sys.stderr.write("lc init: guidance repo not created: %s\n" % r.guidance_refusal)
        return 1
    return 0


def _init_pull_default_origin():
    origin = container().config.default_origin()
    if container().workflow_source.read_registry(origin) is not None:
        return
    try:
        url = container().config.workflows_remote()
    except ConfigError:
        sys.stderr.write(
            "workflows-remote is not set; run `lc config --edit` to set it, then "
            "`lc workflow add <url> --name %s`\n" % origin
        )
        return
    try:
        resp = AddWorkflowSourceUseCase(
            container().workflow_source, container().store, container().config, container().fs,
            container().workflow_lifecycle(),
        ).execute(url=url, ref="main", name=origin)
        print("pulled %s workflows @ %s" % (resp.origin, resp.sha))
    except WorkflowSourceError as e:
        sys.stderr.write(
            "could not pull workflows: %s\nrun `lc workflow add %s --name %s` once reachable\n"
            % (e, url, origin))


def cmd_project(argv):
    parser = build_parser(COMMANDS["project"])
    a = parser.parse_args(argv)
    if a.sub is None:
        parser.print_help()
        return 2
    c = container()
    try:
        if a.sub == "add":
            r = AddProjectUseCase(c.store, c.git, c.config, c.fs).execute(
                AddProjectInput(
                    identity=a.identity, shortcode=a.shortcode, path=a.path, facets=a.facets
                )
            )
            if r.changed:
                print("%s -> shortcode %s%s%s" % (
                    r.identity, r.shortcode,
                    " at %s" % r.local_path if r.local_path else " (no local checkout)",
                    " facets %s" % ",".join(r.facets) if r.facets else "",
                ))
            else:
                print("%s already registered (shortcode %s)" % (r.identity, r.shortcode))
            return 0
        if a.sub == "set":
            r = SetProjectUseCase(c.store, c.config).execute(
                a.identity, a.facets, a.shortcode
            )
            if a.shortcode is not None:
                if r.shortcode_changed:
                    print("%s -> shortcode %s" % (r.identity, r.shortcode))
                else:
                    print("%s shortcode unchanged" % r.identity)
            if r.facets_given:
                if not r.changed:
                    print("%s facets unchanged" % r.identity)
                elif r.facets:
                    print("%s -> facets %s" % (r.identity, ",".join(r.facets)))
                else:
                    print("%s -> no facets" % r.identity)
            return 0
        if a.sub == "list":
            for p in ListProjectsUseCase(c.store).execute():
                print("%s\t%s\t%s\t%s" % (
                    p.identity, p.shortcode or "-", p.local_path or "(not checked out)",
                    ",".join(p.facets),
                ))
            return 0
        if a.sub == "rm":
            RemoveProjectUseCase(c.store).execute(a.identity)
            print("removed %s" % a.identity)
            return 0
        if a.sub == "scan":
            result = ScanProjectsUseCase(c.store, c.git, c.config, c.fs).execute(a.dir)
            candidates = result.candidates
            if a.json:
                print(json.dumps([
                    {
                        **{k: v for k, v in cand._asdict().items() if k != "suggested_facets"},
                        "suggested_facets": [
                            {"facet": facet, "file": file} for facet, file in cand.suggested_facets
                        ],
                    }
                    for cand in candidates
                ], indent=2))
                return 0
            for cand in candidates:
                if cand.status == "unreadable":
                    print("unreadable\t%s\t(git could not read this repo)" % cand.path)
                elif cand.status == "no-remote":
                    print("no-remote\t%s\t(%s)" % (cand.path, cand.remote or "no origin"))
                elif cand.status == "already-registered":
                    print("already-registered\t%s\t%s\tproposed %s\tregistered at %s (shortcode %s)" % (
                        cand.identity, cand.path, cand.shortcode,
                        cand.registered_path or "(no local checkout)", cand.registered_shortcode or "-",
                    ))
                else:
                    print("new\t%s\t%s\tshortcode %s" % (cand.identity, cand.path, cand.shortcode))
                for facet, file in cand.suggested_facets:
                    print("  facet\t%s\t%s" % (facet, file))
            if result.no_suggestions_reason:
                print("no facet suggestions: %s" % result.no_suggestions_reason)
            return 0
    except UseCaseError as e:
        sys.stderr.write("%s\n" % e)
        return 1


CONFIG_EDIT_RESTART_NOTICE = (
    "config saved - a running pool (`lc start`) applies it within a tick, except "
    + ", ".join(RESTART_REQUIRED_KEYS)
    + " which need a pool restart; any open TUI (`lc tui`) keeps the old values until restarted"
)


def cmd_config(argv):
    a = build_parser(COMMANDS["config"]).parse_args(argv)
    if a.edit:
        container().config.ensure_config()
        editor = container().config.editor()
        before = container().config.config_mtime()
        rc = container().launcher.edit(editor, container().config.config_path())
        if rc == 0 and container().config.config_mtime() != before:
            print(CONFIG_EDIT_RESTART_NOTICE)
        return rc
    p = container().config.config_path()
    print("config: %s" % p)
    print("exists" if container().fs.exists(p) else "not found - run `lc init` to seed it")
    for s in container().config.resolved_settings():
        if s.key == "personal-origin" and not s.value:
            print("%s: (not set)" % s.key)
        elif s.state == "unset":
            print("%s: (not set - run `lc init`)" % s.key)
        elif s.state == "invalid":
            print("%s: (rejected - %s)" % (s.key, s.error))
        elif s.state == "env":
            print("%s: %s (env: %s)" % (s.key, s.value, s.env_var))
        elif s.seed == "":
            print("%s: %s (no seed)" % (s.key, s.value))
        else:
            print("%s: %s (seed %s)" % (s.key, s.value, s.seed))
    return 0
