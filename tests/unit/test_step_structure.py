from pathlib import Path

from lightcycle.domain.workflows.step_structure import check_step_structure

FRAGMENTS = {"plain-language"}
ROOT = Path(__file__).resolve().parents[2]


def _check(text, name="steps/x.md"):
    return check_step_structure({name: text}, FRAGMENTS).get(name, [])


def test_clean_list_passes():
    assert _check("1. a\n2. b\n3. c\n") == []


def test_restart_is_reported_at_the_restarting_line():
    text = "1. a\n2. b\n3. c\n4. d\n5. e\n\nprose\n\n1. again\n"
    assert _check(text) == ["line 9: top-level list item 1 follows 5 (expected 6)"]


def test_repeat_is_reported_at_the_second_occurrence():
    assert _check("5. a\n") == ["line 1: top-level list starts at 5 (expected 1)"]
    assert _check("1. a\n2. b\n3. c\n4. d\n5. e\n6. f\n6. g\n") == [
        "line 7: top-level list item 6 follows 6 (expected 7)"
    ]


def test_skip_is_reported_at_the_skipping_line():
    assert _check("1. a\n2. b\n4. c\n") == [
        "line 3: top-level list item 4 follows 2 (expected 3)"
    ]


def test_list_starting_at_two_is_reported():
    assert _check("2. a\n3. b\n") == ["line 1: top-level list starts at 2 (expected 1)"]


def test_nested_sublist_is_not_reported():
    assert _check("1. a\n2. b\n3. c\n  1. x\n  2. y\n4. d\n") == []


def test_numbered_lines_in_a_fence_are_not_reported():
    assert _check("1. a\n```\n1. x\n7. y\n```\n2. b\n") == []
    assert _check("~~~\n9. x\n~~~\n1. a\n") == []


def test_headed_sections_each_restart_from_one():
    assert _check("# A\n1. a\n2. b\n3. c\n## B\n1. a\n2. b\n3. c\n") == []


def test_indented_include_is_reported():
    assert _check("a\n  @include plain-language\n") == [
        "line 2: @include plain-language is indented; the engine only resolves it at column 0"
    ]


def test_indented_include_in_a_fence_is_not_reported():
    assert _check("```\n  @include plain-language\n```\n") == []


def test_resolving_include_passes():
    assert _check("@include plain-language\n") == []


def test_unresolvable_include_names_the_available_fragments():
    assert _check("a\n@include missing\n") == [
        "line 2: @include missing does not resolve in a pinned bundle "
        "(available fragments: plain-language)"
    ]


def test_unresolvable_include_in_a_fence_is_still_reported():
    assert _check("```\n@include missing\n```\n") == [
        "line 2: @include missing does not resolve in a pinned bundle "
        "(available fragments: plain-language)"
    ]


def test_mixed_file_reports_exactly_the_broken_ones_in_line_order():
    text = (
        "1. a\n"
        "2. b\n"
        "@include plain-language\n"
        "@include missing\n"
        "2. c\n"
    )
    assert _check(text) == [
        "line 4: @include missing does not resolve in a pinned bundle "
        "(available fragments: plain-language)",
        "line 5: top-level list item 2 follows 2 (expected 3)",
    ]


def test_a_sound_file_is_absent_from_the_result():
    assert check_step_structure({"steps/a.md": "1. a\n", "steps/b.md": "1. a\n1. b\n"}, FRAGMENTS).keys() == {
        "steps/b.md"
    }


def test_worked_example_from_the_spec():
    text = "1. a\n2. b\n\n6. c\n  1. nested\n7. d\n"
    assert _check(text) == ["line 4: top-level list item 6 follows 2 (expected 3)"]


def _real_fragment_names():
    return {p.stem for p in (ROOT / "lightcycle" / "prompts" / "fragments").glob("*.md")}


def _all_clean(directory):
    files = sorted(directory.glob("*.md"))
    assert files
    texts = {"steps/%s" % p.name: p.read_text() for p in files}
    assert check_step_structure(texts, _real_fragment_names()) == {}


def test_engine_step_files_are_sound():
    _all_clean(ROOT / "lightcycle" / "prompts" / "steps")


def test_library_step_files_are_sound():
    _all_clean(ROOT / "tests" / "support" / "library" / "steps")


def test_union_of_engine_and_origin_fragment_names_resolves_both():
    assert check_step_structure(
        {"s": "@include plain-language\n@include x\n"}, {"plain-language", "x"}
    ) == {}
