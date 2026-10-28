def problem_lines(problems) -> list:
    lines = []
    for problem in problems:
        suffix = " (%s)" % problem.node_id if problem.node_id else ""
        lines.append("  %s%s" % (problem.message, suffix))
        if problem.fix:
            lines.append("    fix: %s" % problem.fix)
    return lines
