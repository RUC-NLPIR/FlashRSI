"""Contract tests for the pure-Python Pi runtime resources and tools."""

import json
import shutil
from pathlib import Path

import pytest

from flashrsi.agents.pi_agent.runtime.pi_native import (
    default_tools,
    execute_tool,
    expand_prompt_template,
    load_resources,
    substitute_template,
    tool_schemas,
)
from flashrsi.agents.pi_agent.runtime.pi_native.tools import (
    truncate_head,
    truncate_tail,
)


def test_pi_native_tools_edit_read_and_bash(tmp_path):
    target = tmp_path / "note.txt"
    target.write_text("before\n", encoding="utf-8")

    edited = execute_tool(
        "edit",
        {
            "path": "note.txt",
            "edits": [{"oldText": "before", "newText": "after"}],
        },
        tmp_path,
    )
    assert not edited.is_error
    assert target.read_text(encoding="utf-8") == "after\n"
    assert "after" in execute_tool("read", {"path": "note.txt"}, tmp_path).content

    result = execute_tool("bash", {"command": "printf native"}, tmp_path)
    assert not result.is_error
    assert result.content == "native"


def test_pi_native_edit_accepts_legacy_and_json_string_shapes(tmp_path):
    target = tmp_path / "note.txt"
    target.write_text("one two\n", encoding="utf-8")

    legacy = execute_tool(
        "edit",
        {"path": "note.txt", "oldText": "one", "newText": "ONE"},
        tmp_path,
    )
    assert not legacy.is_error
    encoded = execute_tool(
        "edit",
        {
            "path": "note.txt",
            "edits": '[{"oldText":"two","newText":"TWO"}]',
        },
        tmp_path,
    )
    assert not encoded.is_error
    assert target.read_text(encoding="utf-8") == "ONE TWO\n"
    assert encoded.details["patch"]


def test_pi_read_untruncated_result_has_no_truncation_details(tmp_path):
    (tmp_path / "note.txt").write_text("plain text\n", encoding="utf-8")
    result = execute_tool("read", {"path": "note.txt"}, tmp_path)
    assert result.details == {}


def test_pi_edit_details_match_executed_upstream_bom_crlf_trace(tmp_path):
    # Captured from original Pi v1.4.0 read/edit tools in
    # runs/pi-parity-20261031/reference.json, case fuzzy_edit_bom_crlf.
    target = tmp_path / "note.txt"
    target.write_bytes("\ufeffkeep   \r\nfirst target   \r\nlast   \r\n".encode())
    result = execute_tool(
        "edit",
        {
            "path": "note.txt",
            "edits": [{"oldText": "first target\n", "newText": "FIRST\nSECOND\n"}],
        },
        tmp_path,
    )
    assert not result.is_error
    assert result.details == {
        "diff": " 1 keep   \n-2 first target   \n+2 FIRST\n+3 SECOND\n 3 last   ",
        "patch": (
            "--- note.txt\n+++ note.txt\n@@ -1,3 +1,4 @@\n"
            " keep   \n-first target   \n+FIRST\n+SECOND\n last   \n"
        ),
        "firstChangedLine": 2,
    }
    assert (
        target.read_bytes()
        == "\ufeffkeep   \r\nFIRST\r\nSECOND\r\nlast   \r\n".encode()
    )


def test_pi_edit_patch_matches_upstream_missing_final_newline(tmp_path):
    target = tmp_path / "note.txt"
    target.write_text("hello", encoding="utf-8")
    result = execute_tool(
        "edit",
        {"path": "note.txt", "edits": [{"oldText": "hello", "newText": "world"}]},
        tmp_path,
    )
    assert result.details == {
        "diff": "-1 hello\n+1 world",
        "patch": (
            "--- note.txt\n+++ note.txt\n@@ -1,1 +1,1 @@\n"
            "-hello\n\\ No newline at end of file\n"
            "+world\n\\ No newline at end of file\n"
        ),
        "firstChangedLine": 1,
    }


def test_pi_edit_display_diff_matches_upstream_four_line_context(tmp_path):
    target = tmp_path / "note.txt"
    target.write_text("".join(f"line {n}\n" for n in range(1, 26)), encoding="utf-8")
    result = execute_tool(
        "edit",
        {
            "path": "note.txt",
            "edits": [
                {"oldText": "line 7\n", "newText": "SEVEN\n"},
                {"oldText": "line 20\n", "newText": "TWENTY\n"},
            ],
        },
        tmp_path,
    )
    assert result.details["diff"] == (
        "    ...\n  3 line 3\n  4 line 4\n  5 line 5\n  6 line 6\n"
        "- 7 line 7\n+ 7 SEVEN\n  8 line 8\n  9 line 9\n 10 line 10\n 11 line 11\n"
        "    ...\n 16 line 16\n 17 line 17\n 18 line 18\n 19 line 19\n"
        "-20 line 20\n+20 TWENTY\n 21 line 21\n 22 line 22\n 23 line 23\n 24 line 24\n    ..."
    )
    assert "@@ -3,9 +3,9 @@" in result.details["patch"]
    assert "@@ -16,9 +16,9 @@" in result.details["patch"]


def test_pi_native_resources_build_prompt_and_templates(tmp_path):
    (tmp_path / "AGENTS.md").write_text("snapshot instructions", encoding="utf-8")
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "extra.md").write_text("extra prompt", encoding="utf-8")
    skill_dir = tmp_path / ".pi" / "agent" / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Demonstrate a skill\n---\nUse the demo skill.",
        encoding="utf-8",
    )
    template_dir = tmp_path / ".pi" / "agent" / "prompt-templates"
    template_dir.mkdir(parents=True)
    (template_dir / "review.md").write_text(
        "---\ndescription: Review files\n---\nReview $1 and $@.",
        encoding="utf-8",
    )

    bundle = load_resources(tmp_path, tmp_path, selected_tools=["read", "bash"])
    assert "snapshot instructions" in bundle.system_prompt
    assert "extra prompt" in bundle.system_prompt
    assert "demo" in bundle.system_prompt
    assert "Review files" == bundle.templates["review"].description
    assert substitute_template(
        bundle.templates["review"].content, ["a.py", "b.py"]
    ) == ("Review a.py and a.py b.py.")
    assert [item["function"]["name"] for item in bundle.tool_schemas] == [
        "read",
        "bash",
    ]


def test_pi_skills_load_loose_markdown_only_at_search_root(tmp_path):
    skills = tmp_path / ".pi" / "agent" / "skills"
    nested = skills / "nested"
    nested.mkdir(parents=True)
    for path, name in [
        (skills / "review.md", "review"),
        (nested / "other.md", "other"),
    ]:
        path.write_text(
            f"---\nname: {name}\ndescription: A {name} skill\n---\n{name} instructions\n",
            encoding="utf-8",
        )

    bundle = load_resources(tmp_path, tmp_path)

    assert [skill.name for skill in bundle.skills] == ["review"]
    assert bundle.skills[0].path == str(skills / "review.md")
    assert "A review skill" in bundle.system_prompt
    assert "A other skill" not in bundle.system_prompt


@pytest.mark.parametrize("declared_directory", ["", "parent"])
def test_pi_declared_skill_stops_discovery_inside_its_directory(
    tmp_path, declared_directory
):
    skills = tmp_path / ".pi" / "agent" / "skills"
    declared = skills / declared_directory
    child = declared / "a-child"
    child.mkdir(parents=True)
    for path, name in [
        (skills / "loose.md", "loose"),
        (declared / "SKILL.md", "declared"),
        (child / "SKILL.md", "child"),
    ]:
        path.write_text(
            f"---\nname: {name}\ndescription: A {name} skill\n---\n{name} instructions\n",
            encoding="utf-8",
        )

    bundle = load_resources(tmp_path, tmp_path)

    expected = ["declared"] if not declared_directory else ["loose", "declared"]
    assert [skill.name for skill in bundle.skills] == expected
    assert "A declared skill" in bundle.system_prompt
    assert "A child skill" not in bundle.system_prompt


def test_pi_native_settings_and_prompt_invocation(tmp_path):
    settings = tmp_path / ".pi" / "agent"
    settings.mkdir(parents=True)
    (settings / "settings.json").write_text(
        '{"defaultTools": ["read", "grep"]}', encoding="utf-8"
    )
    templates = settings / "prompt-templates"
    templates.mkdir()
    (templates / "review.md").write_text("Review $1", encoding="utf-8")
    bundle = load_resources(tmp_path, tmp_path)
    assert default_tools(tmp_path) == ["read", "grep"]
    assert expand_prompt_template("/review app.py", bundle.templates) == "Review app.py"

    (settings / "settings.json").write_text('{"defaultTools": []}', encoding="utf-8")
    empty_bundle = load_resources(tmp_path, tmp_path, selected_tools=[])
    assert empty_bundle.tool_schemas == []


def test_pi_prompt_template_parser_preserves_empty_quoted_arguments(tmp_path):
    template_dir = tmp_path / ".pi" / "agent" / "prompt-templates"
    template_dir.mkdir(parents=True)
    (template_dir / "args.md").write_text("$1|$2|$@", encoding="utf-8")
    bundle = load_resources(tmp_path, tmp_path)
    assert (
        expand_prompt_template('/args "" second', bundle.templates) == "|second| second"
    )


def test_pi_native_tool_schemas_are_openai_function_declarations():
    schemas = tool_schemas(["read", "grep", "ls"])
    assert [schema["type"] for schema in schemas] == ["function"] * 3
    assert [schema["function"]["name"] for schema in schemas] == [
        "read",
        "grep",
        "ls",
    ]


def test_pi_truncation_keeps_upstream_trailing_newline_limit_label():
    content, details = truncate_head("hello\nworld\n", max_lines=2, max_bytes=11)
    assert content == "hello\nworld"
    assert details["truncated_by"] == "lines"
    assert details["total_lines"] == 2
    assert details["output_lines"] == 2


def test_pi_truncation_matches_executed_upstream_oracle():
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "pi_tools_upstream.json").read_text()
    )
    for case in fixture["truncation"]:
        truncate = truncate_head if case["direction"] == "head" else truncate_tail
        content, details = truncate(
            case["input"], max_lines=case["maxLines"], max_bytes=case["maxBytes"]
        )
        expected = case["expected"]
        assert content == expected["content"], case
        for key, value in details.items():
            parts = key.split("_")
            upstream_key = parts[0] + "".join(part.title() for part in parts[1:])
            assert value == expected[upstream_key], (case, key)


def test_pi_edit_matches_executed_upstream_matching_oracle(tmp_path):
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "pi_tools_upstream.json").read_text()
    )
    target = tmp_path / "note.txt"
    for case in fixture["edits"]:
        target.write_text(case["input"], encoding="utf-8", newline="")
        result = execute_tool(
            "edit", {"path": "note.txt", "edits": case["edits"]}, tmp_path
        )
        expected = case["expected"]
        assert result.is_error == expected["isError"], case["name"]
        if expected["isError"]:
            assert result.content == expected["error"], case["name"]
            assert target.read_text() == case["input"], case["name"]
        else:
            assert target.read_text() == expected["newContent"], case["name"]


def test_pi_bash_timeout_preserves_partial_output(tmp_path):
    result = execute_tool(
        "bash", {"command": "printf before; exec sleep 1", "timeout": 0.05}, tmp_path
    )
    assert result.is_error
    assert result.content == "before\n\nCommand timed out after 0.05 seconds"


@pytest.mark.parametrize("login_shell", ["/bin/zsh", None])
def test_pi_bash_uses_bash_independently_of_login_shell(
    tmp_path, monkeypatch, login_shell
):
    bash = "/bin/bash" if Path("/bin/bash").exists() else shutil.which("bash")
    if bash is None:
        pytest.skip("Bash is not installed")
    if login_shell is None:
        monkeypatch.delenv("SHELL", raising=False)
    else:
        monkeypatch.setenv("SHELL", login_shell)

    result = execute_tool(
        "bash",
        {"command": 'values=(one two); printf \'%s|%s\' "$BASH" "${values[1]}"'},
        tmp_path,
    )

    assert not result.is_error, result.content
    assert result.content == f"{bash}|two"


def test_pi_fuzzy_edit_preserves_unmodified_lines_when_replacement_adds_lines(tmp_path):
    target = tmp_path / "notes.txt"
    target.write_text("keep   \nfirst target   \nlast   \n", encoding="utf-8")

    result = execute_tool(
        "edit",
        {
            "path": "notes.txt",
            "edits": [
                {"oldText": "first target\n", "newText": "FIRST\nSECOND\n"},
            ],
        },
        tmp_path,
    )

    assert not result.is_error
    assert target.read_text(encoding="utf-8") == "keep   \nFIRST\nSECOND\nlast   \n"


def test_pi_edit_normalizes_bare_cr_line_endings_like_upstream(tmp_path):
    target = tmp_path / "old-mac.txt"
    target.write_bytes(b"first\rsecond\r")
    result = execute_tool(
        "edit",
        {
            "path": "old-mac.txt",
            "edits": [{"oldText": "second\n", "newText": "SECOND\n"}],
        },
        tmp_path,
    )
    assert not result.is_error
    assert target.read_bytes() == b"first\nSECOND\n"


def test_pi_prompt_substitution_matches_upstream_edge_cases():
    cases = [
        ("$1 $2 $3 $4 $5", ["a", "b"], "a b   "),
        ("$0", ["a", "b"], ""),
        ("${0:-fallback}", ["a", "b"], "fallback"),
        ("${1:-$ARGUMENTS}", ["a", "b"], "a"),
        ("${3:-$ARGUMENTS}", ["a", "b"], "$ARGUMENTS"),
        ("${@:0}", ["a", "b", "c"], "a b c"),
        ("${@:2:0}", ["a", "b", "c"], ""),
        ("${@:2:99}", ["a", "b", "c"], "b c"),
        ("$ARGUMENTS", ["$1", "$ARGUMENTS"], "$1 $ARGUMENTS"),
        ("Price: \\$100", [], "Price: \\"),
    ]
    for content, args, expected in cases:
        assert substitute_template(content, args) == expected


def test_pi_prompt_argument_parser_and_frontmatter_match_upstream(tmp_path):
    agent_dir = tmp_path / ".pi" / "agent"
    template_dir = agent_dir / "prompt-templates"
    template_dir.mkdir(parents=True)
    (template_dir / "args.md").write_text(
        '---\r\ndescription: a prompt\r\nargument-hint: ""\r\n---\r\n$1|$2|$@\r\n',
        encoding="utf-8",
    )
    (template_dir / "long.md").write_text("x" * 61 + "\n", encoding="utf-8")
    bundle = load_resources(tmp_path, tmp_path)
    args_template = bundle.templates["args"]
    assert args_template.content == "$1|$2|$@"
    assert args_template.argument_hint is None
    assert (
        expand_prompt_template('/args "" second', bundle.templates) == "|second| second"
    )
    assert expand_prompt_template(
        "/args\nlabel-2\n\nHere is some description #2.", bundle.templates
    ) == ("label-2|Here|label-2 Here is some description #2.")
    assert bundle.templates["long"].description == "x" * 60 + "..."


def test_pi_prompt_invalid_frontmatter_is_skipped_with_diagnostic(tmp_path):
    template_dir = tmp_path / ".pi" / "agent" / "prompt-templates"
    template_dir.mkdir(parents=True)
    (template_dir / "invalid.md").write_text(
        "---\ndescription: Broken: unquoted colon\n---\nDo something.\n",
        encoding="utf-8",
    )
    (template_dir / "valid.md").write_text("Valid prompt content.", encoding="utf-8")

    bundle = load_resources(tmp_path, tmp_path)
    assert list(bundle.templates) == ["valid"]
    assert any(
        "invalid.md" in message and "parse" in message for message in bundle.diagnostics
    )
