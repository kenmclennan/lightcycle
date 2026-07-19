from lightcycle.application.errors import UseCaseError


def validate_title(config, title):
    cap = config.max_title_length()
    if title and len(title) > cap:
        raise UseCaseError(
            "title exceeds %d chars; keep the title a short summary and put detail in "
            "--description" % cap
        )
