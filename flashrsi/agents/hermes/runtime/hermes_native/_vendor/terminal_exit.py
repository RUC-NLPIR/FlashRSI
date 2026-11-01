"""Original pure exit-code interpretation from Hermes v0.22.5."""

import re
import signal


_SIGNAL_EXIT_NOTES: dict[int, str] = {
    3:  "SIGQUIT (quit from keyboard)",
    4:  "SIGILL (illegal instruction — corrupt binary or wrong architecture)",
    6:  "SIGABRT (abort — assertion failure, fatal runtime error, or glibc abort)",
    7:  "SIGBUS (bus error — misaligned or unmapped memory access)",
    8:  "SIGFPE (fatal arithmetic error, e.g. integer division by zero)",
    9:  "SIGKILL — often the kernel OOM killer on memory exhaustion, or an explicit kill -9",
    11: "SIGSEGV (segmentation fault — the program crashed)",
    13: "SIGPIPE (wrote to a closed pipe — e.g. output piped to a reader that exited)",
    15: "SIGTERM (terminated — kill/timeout or shutdown requested it to stop)",
    24: "SIGXCPU (CPU time limit exceeded)",
    25: "SIGXFSZ (file size limit exceeded)",
}

def _interpret_signal_exit(exit_code: int) -> str | None:
    """Note for a signal-termination exit code, or None. Negative codes are
    definite (subprocess semantics); 128+signum is the shell convention and a
    program *can* exit 139 itself, so those notes hedge with "usually"."""
    if exit_code < 0:
        signum = -exit_code
        if signum == 2:  # SIGINT — executor's interrupt-marker path owns it
            return None
        if note := _SIGNAL_EXIT_NOTES.get(signum):
            return f"Command terminated by signal {signum}: {note}"
        try:
            name = signal.Signals(signum).name
        except ValueError:
            name = f"signal {signum}"
        return f"Command terminated by {name} (signal {signum})"
    if exit_code > 128 and (note := _SIGNAL_EXIT_NOTES.get(exit_code - 128)):
        return (f"Exit code {exit_code} usually means the command was "
                f"terminated by signal {exit_code - 128}: {note}")
    return None

_EXIT_CODE_SEMANTICS: dict[str, dict[int, str]] = {
    **{key: {1: "No matches found (not an error)"} for key in ("grep", "egrep", "fgrep", "rg", "ag", "ack")},
    **{key: {1: "Files differ (expected, not an error)"} for key in ("diff", "colordiff")},
    **{key: {1: "Condition evaluated to false (expected, not an error)"} for key in ("test", "[")},
    "find": {1: "Some directories were inaccessible (partial results may still be valid)"},
    "curl": {6: "Could not resolve host", 7: "Failed to connect to host",
             22: "HTTP response code indicated error (e.g. 404, 500)", 28: "Operation timed out"},
    "git": {1: "Non-zero exit (often normal — e.g. 'git diff' returns 1 when files differ)"},
}

def _interpret_exit_code(command: str, exit_code: int) -> str | None:
    """Note for a non-zero exit code that is informational rather than an
    error (grep=1 "no matches", diff=1 "files differ", signal deaths), so the
    model doesn't burn turns investigating it. None when 0 or a real error."""
    if exit_code == 0:
        return None
    if (signal_note := _interpret_signal_exit(exit_code)) is not None:
        # Signal terminations (ported from Kilo-Org/kilocode#12698, adapted to Python semantics). Two shapes
        # reach the model: * negative codes — subprocess.Popen reports a signal-killed process as
        # ``-signum`` (definite signal death), and * 128+signum — the conventional shell encoding when bash
        # reports a signal-killed child (heuristic: a program *can* ``exit 139``, so these notes say
        # "usually"). Without a note the model sees a bare ``exit_code=-9`` or ``137`` and burns turns
        # re-running or mis-diagnosing (137 = OOM kill is the big one). 130/SIGINT is deliberately absent:
        # the executor has bespoke interrupt-marker handling for rc=130.
        return signal_note
    # The last command of a pipeline/chain determines the exit code; base
    # command = its first word that isn't a VAR=val assignment, basename'd.
    segments = re.split(r'\s*(?:\|\||&&|[|;])\s*', command)
    last_segment = (segments[-1] if segments else command).strip()
    base_cmd = next((w.split("/")[-1] for w in last_segment.split()
                     if "=" not in w or w.startswith("-")), "")
    return _EXIT_CODE_SEMANTICS.get(base_cmd, {}).get(exit_code)
