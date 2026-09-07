from lightcycle.application.work.project_of import project_of, short_project_label


def project_matches(store, item, short_ref):
    if short_ref is None:
        return True
    raw = project_of(store, item)
    return raw is not None and raw.rsplit("/", 1)[-1] == short_ref


def text_matches(store, item, needle):
    if not needle:
        return True
    project = short_project_label(project_of(store, item))
    haystack = "%s %s %s" % (item.id, item.title, project)
    return needle.lower() in haystack.lower()
