import json

import pytest

from flashrsi.algorithms.skillopt._patch import (
    _apply_guidance,
    _field,
    _Patch,
    _PatchError,
    _ranked,
    _replace_section,
    _section,
)


def patch(*edits, source_type=""):
    return _Patch.parse(
        json.dumps(
            {
                "patch": {
                    "reasoning": "shared pattern",
                    "edits": [{"path": "skills/main.md", **edit} for edit in edits],
                }
            }
        ),
        source_type,
    )


def apply_text(proposal, text, budget):
    return proposal.apply({"skills/main.md": text}, budget)["skills/main.md"]


def test_nested_and_fenced_patch_labels_the_evidence_source():
    proposal = patch(
        {"op": "append", "content": "Verify evidence.", "source_type": "failure"},
        source_type="success",
    )
    restored = _Patch.parse(f"```json\n{json.dumps(proposal.as_mapping())}\n```")
    assert restored == proposal
    assert proposal.edits[0].source_type == "success"


def test_anchored_edits_apply_in_sequence_and_preserve_unrelated_whitespace():
    proposal = patch(
        {"op": "insert_after", "target": "# Skill", "content": "Check sources."},
        {"op": "replace", "target": "Check sources.", "content": "Verify sources."},
        {"op": "delete", "target": "Old rule.\n"},
        {"op": "append", "content": "Cite evidence."},
    )
    assert apply_text(proposal, "  # Skill\nOld rule.\n", 4) == (
        "  # Skill\nVerify sources.\n\nCite evidence.\n"
    )
    with pytest.raises(_PatchError, match="budget"):
        apply_text(proposal, "# Skill\nOld rule.\n", 3)


def test_empty_and_identical_patches_preserve_exact_text():
    original = "  # Skill\n\nRule.  \n\n"
    assert apply_text(patch(), original, 1) == original
    assert (
        apply_text(
            patch({"op": "replace", "target": "Rule.", "content": "Rule."}),
            original,
            1,
        )
        == original
    )


@pytest.mark.parametrize("original", ["No anchor.", "rule then rule"])
def test_missing_or_ambiguous_anchor_is_rejected(original):
    with pytest.raises(_PatchError, match="exactly once"):
        apply_text(patch({"op": "delete", "target": "rule"}), original, 1)


def test_overlapping_anchor_matches_are_ambiguous():
    with pytest.raises(_PatchError, match="exactly once"):
        apply_text(patch({"op": "replace", "target": "aa", "content": "b"}), "aaa", 1)


@pytest.mark.parametrize(
    "response",
    [
        "not json",
        "[]",
        '{"patch": []}',
        '{"edits": {}}',
        '{"edits": [null]}',
        '{"edits": [], "reasoning": 5}',
        '{"edits": [{"op": "write", "content": "x"}]}',
        '{"edits": [{"op": "append", "content": " "}]}',
        '{"edits": [{"op": "delete", "target": ""}]}',
        '{"edits": [{"op": "replace", "target": "x", "content": 1}]}',
        '{"edits": [{"op": "append", "content": "x", "support_count": true}]}',
    ],
)
def test_invalid_worker_patch_fails_explicitly(response):
    with pytest.raises(_PatchError):
        _Patch.parse(response)


def test_fast_update_cannot_mutate_or_create_the_slow_update_section():
    original = _replace_section("# Skill\n", "Protected guidance.")
    for edit in (
        {"op": "replace", "target": "Protected guidance.", "content": "Changed."},
        {"op": "delete", "target": _section(original)},
        {"op": "insert_after", "target": "Protected guidance.", "content": "New."},
        {"op": "append", "content": _section(original)},
    ):
        with pytest.raises(_PatchError):
            apply_text(patch(edit), original, 1)
    with pytest.raises(_PatchError):
        apply_text(patch({"op": "append", "content": _section(original)}), "# Skill", 1)
    result = apply_text(
        patch({"op": "append", "content": "Ordinary rule."}), original, 1
    )
    assert _section(result) == _section(original)


@pytest.mark.parametrize(
    "original",
    [
        "<!-- SLOW_UPDATE_START -->",
        "<!-- SLOW_UPDATE_END -->",
        "<!-- SLOW_UPDATE_END --><!-- SLOW_UPDATE_START -->",
        "<!-- SLOW_UPDATE_START --><!-- SLOW_UPDATE_END -->" * 2,
    ],
)
def test_unbalanced_or_duplicate_protected_markers_fail(original):
    with pytest.raises(_PatchError, match="balanced"):
        _replace_section(original, "guidance")


def test_slow_update_preserves_surroundings_and_has_one_region():
    original = "  Intro.\n\n" + _replace_section("", "Old.") + "\nSuffix.  "
    replacement = _replace_section(original, "New.")
    assert replacement == original.replace("Old.", "New.")
    assert _replace_section(replacement, "New.") == replacement
    assert replacement.count("<!-- SLOW_UPDATE_START -->") == 1
    with pytest.raises(_PatchError, match="omit"):
        _replace_section(original, "<!-- SLOW_UPDATE_START -->\ninvalid")


def test_selection_preserves_requested_order_and_evidence():
    proposal = patch(
        {"op": "append", "content": "Fix.", "support_count": 3},
        {"op": "append", "content": "Repeat.", "source_type": "success"},
        {"op": "append", "content": "Drop."},
    )
    selected = proposal.select((1, 0))
    assert selected.edits == (proposal.edits[1], proposal.edits[0])
    assert selected.reasoning == proposal.reasoning


def test_slow_and_rank_responses_require_the_requested_schema():
    assert _field('{"slow_update_content": "  Check.  "}', "slow_update_content") == (
        "Check."
    )
    assert _ranked('{"selected_indices": [2, 0]}', size=3, limit=2) == (2, 0)
    assert _ranked('{"selected_indices": []}', size=3, limit=2) == ()
    with pytest.raises(_PatchError, match="string"):
        _field('{"slow_update_content": 1}', "slow_update_content")
    for indices in ([1, 1], [3], [-1], [True], [0, 1, 2]):
        with pytest.raises(_PatchError):
            _ranked(json.dumps({"selected_indices": indices}), size=3, limit=2)


def test_multifile_patch_applies_atomically_and_can_create_a_skill():
    original = {"skills/a.md": "Old guidance.", "skills/b.md": "Keep this.\n"}
    proposal = patch(
        {"path": "skills/a.md", "op": "replace", "target": "Old", "content": "New"},
        {"path": "skills/new/SKILL.md", "op": "append", "content": "New skill."},
    )
    result = proposal.apply(original, 2)
    assert result == {
        **original,
        "skills/a.md": "New guidance.",
        "skills/new/SKILL.md": "New skill.\n",
    }
    assert original["skills/a.md"] == "Old guidance."
    failing = patch(
        {"path": "skills/a.md", "op": "replace", "target": "Old", "content": "New"},
        {"path": "skills/b.md", "op": "delete", "target": "Missing"},
    )
    with pytest.raises(ValueError, match="exactly once"):
        failing.apply(original, 2)
    assert original["skills/a.md"] == "Old guidance."
    assert patch().apply(original, 2) == original


@pytest.mark.parametrize(
    "path",
    [
        "../escape",
        "/absolute",
        "a//b",
        "a/./b",
        "a/../b",
        "a\\b",
        "C:/file",
        "nul\x00name",
        "",
    ],
)
def test_patch_rejects_unsafe_paths(path):
    with pytest.raises(ValueError, match="path"):
        patch({"path": path, "op": "append", "content": "x"})


def test_fast_edit_cannot_anchor_across_protected_section_even_if_preserved():
    original = _replace_section("Intro.", "Protected.")
    with pytest.raises(ValueError, match="SLOW_UPDATE"):
        apply_text(
            patch(
                {"op": "replace", "target": original, "content": original + " Extra."}
            ),
            original,
            1,
        )


def test_slow_guidance_rewrites_only_named_files_and_leaves_input_unchanged():
    original = {"skills/a.md": "First.", "skills/b.md": "Second."}
    result = _apply_guidance(
        original,
        json.dumps({"guidance": [{"path": "skills/a.md", "content": "New guidance"}]}),
    )
    assert "New guidance" in result["skills/a.md"]
    assert result["skills/b.md"] == original["skills/b.md"]
    assert original["skills/a.md"] == "First."
    assert _apply_guidance(original, '{"guidance": []}') == original


@pytest.mark.parametrize(
    "guidance",
    [
        None,
        {},
        [None],
        [{"path": "missing.md", "content": "x"}],
        [{"path": "skills/a.md", "content": 1}],
        [{"path": "skills/a.md", "content": "x"}] * 2,
    ],
)
def test_slow_guidance_requires_existing_unique_text_paths(guidance):
    with pytest.raises(ValueError, match="guidance"):
        _apply_guidance({"skills/a.md": "text"}, json.dumps({"guidance": guidance}))
