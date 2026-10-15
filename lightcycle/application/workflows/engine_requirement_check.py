from lightcycle.domain.workflows.source import parse_source_manifest


def unmet_requirement_message(requirement, engine_version):
    return (
        "bundle requires engine %s, running engine is %s; run `lc upgrade` "
        "or use a ref that supports this engine" % (requirement.describe(), engine_version)
    )


def bundle_conflict_messages(source):
    for origin in source.list_origins():
        registry = source.read_registry(origin)
        if registry is None or not registry.current:
            continue
        if not source.has_version(origin, registry.current):
            continue
        manifest_text = source.read_manifest(source.pinned_bundle(origin, registry.current))
        yield origin, registry.current, manifest_text


def installed_bundle_conflicts(source, target_version):
    messages = []
    for origin, sha, manifest_text in bundle_conflict_messages(source):
        try:
            manifest = parse_source_manifest(manifest_text)
        except ValueError as e:
            messages.append("origin %s bundle %s has a malformed manifest: %s" % (origin, sha, e))
            continue
        requirement = manifest.requires_engine
        if requirement is not None and not requirement.satisfied_by(target_version):
            messages.append(
                "origin %s bundle %s requires engine %s, which excludes %s"
                % (origin, sha, requirement.describe(), target_version))
    return messages
