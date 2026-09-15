from lightcycle.application.work.project_of import short_project_label, short_repo_label
from lightcycle.domain.work import ProjectIdentity


def project_matches(item, short_ref):
    if short_ref is None:
        return True
    return item.project is not None and ProjectIdentity.short_name(item.project) == short_ref


def text_matches(item, needle):
    if not needle:
        return True
    haystack = "%s %s %s %s" % (
        item.id, item.title, short_project_label(item.project), short_repo_label(item.repo),
    )
    return needle.lower() in haystack.lower()
