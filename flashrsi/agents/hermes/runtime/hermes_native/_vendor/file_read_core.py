"""Original native-read/presentation methods extracted from Hermes ShellFileOperations.

Only import paths are changed. LocalFileOperations supplies task-local I/O hooks.
"""
import base64
import difflib
import hashlib
import json
import os
import unicodedata
from typing import Optional
from .binary_extensions import has_binary_extension
from .file_operations_common import ExecuteResult, ReadResult, PatchResult, _strip_bom, _strip_terminal_fence_leaks
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.ico'}
_MAGIC_SIGNATURES: tuple = (
    # (prefix bytes, human name) — ordered, first match wins. Longest
    # prefixes for a shared first byte come first.
    (b"\x89PNG\r\n\x1a\n", "PNG image data"),
    (b"\xff\xd8\xff", "JPEG image data"),
    (b"GIF87a", "GIF image data"),
    (b"GIF89a", "GIF image data"),
    (b"RIFF", "RIFF container (WAV/AVI/WebP family)"),
    (b"%PDF-", "PDF document"),
    (b"PK\x03\x04", "ZIP archive (also docx/xlsx/jar/apk)"),
    (b"PK\x05\x06", "ZIP archive (empty)"),
    (b"\x1f\x8b", "gzip compressed data"),
    (b"BZh", "bzip2 compressed data"),
    (b"\xfd7zXZ\x00", "xz compressed data"),
    (b"7z\xbc\xaf\x27\x1c", "7-Zip archive"),
    (b"\x7fELF", "ELF executable"),
    (b"MZ", "Windows PE executable"),
    (b"\xcf\xfa\xed\xfe", "Mach-O executable (64-bit)"),
    (b"\xca\xfe\xba\xbe", "Mach-O universal binary / Java class"),
    (b"SQLite format 3\x00", "SQLite database"),
    (b"OggS", "Ogg container"),
    (b"fLaC", "FLAC audio"),
    (b"ID3", "MP3 audio (ID3 tag)"),
    (b"\x00\x00\x00", "ISO media container (MP4/MOV family)"),  # ftyp at +4
    (b"BM", "BMP image data"),
    (b"II*\x00", "TIFF image data (little-endian)"),
    (b"MM\x00*", "TIFF image data (big-endian)"),
)

def identify_binary_bytes(sample: bytes) -> str:
    """Best-effort human name for binary content from its magic bytes; never raises.
    The ISO-media entry additionally requires ``ftyp`` at offset 4 (three leading
    NULs alone are too weak a signature)."""
    for prefix, name in _MAGIC_SIGNATURES:
        if sample.startswith(prefix):
            if name.startswith("ISO media") and sample[4:8] != b"ftyp":
                continue
            return name
    return "unknown binary"

def describe_binary_file(sample: Optional[bytes], file_size: int) -> str:
    """One-line binary-file refusal naming the TYPE ("PNG image data, 4.1 KB"), so the
    model gets what-is-this in one read instead of hunting for tools it may lack."""
    kind = identify_binary_bytes(sample or b"")
    if file_size >= 1024 * 1024:
        size = f"{file_size / (1024 * 1024):.1f} MB"
    elif file_size >= 1024:
        size = f"{file_size / 1024:.1f} KB"
    else:
        size = f"{file_size} bytes"
    return f"Binary file ({kind}, {size}) — cannot display as text."

class NativeReadCore:
    _UTF16_MAX_BYTES = 10 * 1024 * 1024
    _UTF16_SAMPLE_BYTES = 512

    @staticmethod
    def _is_likely_binary_bytes(sample: bytes) -> bool:
        """Byte-layer binary detection: text iff valid UTF-8, allowing one incomplete
        multibyte sequence at the very end (artifact of the byte-boundary cut).
        NUL bytes or mid-stream invalid UTF-8 stay read-only so a read→edit→write
        round-trip never rewrites undecodable bytes as U+FFFD; a file that
        legitimately CONTAINS U+FFFD is valid UTF-8 and reads as text.

        See #80308.
        """
        if not sample:
            return False
        if b"\x00" in sample:
            return True
        try:
            sample.decode("utf-8")
            return False
        except UnicodeDecodeError as exc:
            # UTF-8 sequences are at most 4 bytes: an error starting in the
            # last 3 bytes with a clean prefix is a boundary cut, not binary.
            if exc.start >= len(sample) - 3:
                try:
                    sample[: exc.start].decode("utf-8")
                    return False
                except UnicodeDecodeError:
                    pass
            return True

    def _is_image(self, path: str) -> bool:
        return os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS

    def _add_line_numbers(self, content: str, start_line: int = 1) -> str:
        """Prefix each line with a compact ``<n>|`` gutter, clamping long lines. Not
        fixed-width: padding cost ~16% more tokens per line for no accuracy gain in
        A/B, while dropping numbers regressed line-referencing."""
        from .limits import get_max_line_length
        max_line_length = get_max_line_length()
        # A trailing newline terminates the final line — it does not start a new,
        # empty one. Splitting without dropping it rendered a phantom "<N+1>|"
        # gutter line on every newline-terminated file (`cat -n` semantics).
        # Exactly ONE terminator is dropped, so a genuinely selected trailing
        # blank line in a page keeps its own number.
        content = content.removesuffix('\n')
        return '\n'.join(
            f"{i}|{line if len(line) <= max_line_length else line[:max_line_length] + '... [truncated]'}"
            for i, line in enumerate(content.split('\n'), start=start_line))

    def _unified_diff(self, old_content: str, new_content: str, filename: str) -> str:
        return ''.join(difflib.unified_diff(
            old_content.splitlines(keepends=True), new_content.splitlines(keepends=True),
            fromfile=f"a/{filename}", tofile=f"b/{filename}"))

    @staticmethod
    def _not_regular_error(path: str) -> ReadResult:
        """Error for a path that exists but would block if read."""
        return ReadResult(error=(
            f"Cannot read '{path}': not a regular file (directory, dangling symlink, "
            "FIFO, socket, or device). Reading it could block indefinitely."))

    def _exec_python_snippet(self, snippet: str, py: str | None = None) -> ExecuteResult:
        """Run a Python ``snippet`` in the terminal backend's interpreter.

        Base64-encodes the snippet so it survives every shell/quoting layer
        as pure ASCII: Windows ``subprocess`` list-arg quoting and ``bash``
        double-quote processing both eat backslashes, which otherwise
        corrupts Windows paths (``C:\\Users\\x``) and byte literals
        (``b'\\xfe\\xff'``) embedded in a ``-c`` program. ``exec`` decodes
        and runs it unchanged.
        """
        encoded = base64.b64encode(snippet.encode("utf-8")).decode("ascii")
        if py is None:
            py = self._python_interpreter_cmd()
        return self._exec(
            f"{py} -c \"import base64; exec(base64.b64decode('{encoded}').decode())\""
        )

    def _try_read_utf16(self, path: str, offset: int, limit: int,
                        file_size: int) -> Optional[ReadResult]:
        """Read ``path`` as UTF-16 transcoded to UTF-8, or None (caller falls back
        to the binary-file error). Skips known-binary extensions and files over
        10 MiB. ``path`` must already be expanded."""
        if has_binary_extension(path) or file_size > self._UTF16_MAX_BYTES:
            return None
        snippet = (
            "import sys, json, os\n"
            f"p = {json.dumps(path)}\n"
            f"offset = {int(offset)}\n"
            f"limit = {int(limit)}\n"
            f"MAX = {self._UTF16_MAX_BYTES}\n"
            f"SAMPLE = {self._UTF16_SAMPLE_BYTES}\n"
            "try:\n"
            "    size = os.path.getsize(p)\n"
            "    if size > MAX:\n"
            "        print('HERMES_UTF16:NO'); sys.exit(0)\n"
            "    with open(p, 'rb') as f:\n"
            "        data = f.read()\n"
            "    sample = data[:SAMPLE]\n"
            "    enc = None\n"
            "    if sample[:2] == b'\\xfe\\xff':\n"
            "        enc = 'utf-16-be'\n"
            "    elif sample[:2] == b'\\xff\\xfe':\n"
            "        enc = 'utf-16-le'\n"
            "    else:\n"
            "        odd = sum(1 for i in range(1, len(sample), 2) if sample[i] == 0)\n"
            "        even = sum(1 for i in range(0, len(sample), 2) if sample[i] == 0)\n"
            "        if even == 0 and odd >= 2:\n"
            "            enc = 'utf-16-le'\n"
            "        elif odd == 0 and even >= 2:\n"
            "            enc = 'utf-16-be'\n"
            "    if enc is None:\n"
            "        print('HERMES_UTF16:NO'); sys.exit(0)\n"
            "    text = data.decode(enc, 'replace')\n"
            "    if text[:1] == '\\ufeff':\n"
            "        text = text[1:]\n"
            "    text = text.replace('\\r\\n', '\\n')\n"
            "    lines = text.split('\\n')\n"
            "    total = len(lines)\n"
            "    sel = lines[offset - 1: offset - 1 + limit]\n"
            "    out = {'total_lines': total, 'encoding': enc,\n"
            "           'content': '\\n'.join(sel)}\n"
            "    print('HERMES_UTF16:OK')\n"
            "    print(json.dumps(out, ensure_ascii=True))\n"
            "except Exception:\n"
            "    print('HERMES_UTF16:NO'); sys.exit(0)\n"
        )

        result = self._exec_python_snippet(snippet)
        if result.exit_code != 0 and "python3" in (result.stdout or ""):
            result = self._exec_python_snippet(snippet, py="python")

        stdout = _strip_terminal_fence_leaks(result.stdout or "")
        marker = stdout.find("HERMES_UTF16:OK")
        if result.exit_code != 0 or marker < 0:
            return None
        payload = stdout[marker + len("HERMES_UTF16:OK"):].strip()
        try:
            data = json.loads(payload.split("\n", 1)[0] if "\n" in payload else payload)
            content = data["content"]
            total_lines = int(data["total_lines"])
            encoding = str(data.get("encoding", "utf-16"))
        except (ValueError, KeyError, TypeError):
            return None
        end_line = offset + limit - 1
        truncated = total_lines > end_line
        hint_parts = [f"Transcoded from {encoding.upper()} to UTF-8 for display. "
                      "Text edits via patch/write_file would re-encode as UTF-8."]
        if truncated:
            hint_parts.append(
                f"Use offset={end_line + 1} to continue reading "
                f"(showing {offset}-{end_line} of {total_lines} lines)")
        from .limits import get_max_line_length
        max_line_length = get_max_line_length()
        truncated_lines = any(len(line) > max_line_length for line in content.split('\n'))
        return ReadResult(
            content=self._add_line_numbers(content, offset), total_lines=total_lines,
            file_size=file_size, truncated=truncated, hint=" ".join(hint_parts),
            truncated_lines=True if truncated_lines else None)

    def _read_file_native(self, path: str, offset: int, limit: int) -> ReadResult:
        """``read_file`` without a shell — same contract as the shell path, byte for
        byte. ``os.stat`` is the ``[ -f ]`` guard (a stat, never an open, so FIFOs and
        devices are refused before anything touches them); the first 1000 bytes drive
        the byte-layer binary check; the page is produced exactly as
        ``sed -n 'a,bp' | cut -b1-N`` prints it (each line clamped to N bytes and
        newline-terminated) then decoded with errors="replace" like the transport.
        One chunked pass counts lines and collects the page, so neither the file nor
        a pathological line is ever held whole. ``path`` is already expanded; any
        unexpected OSError hands over to the shell path."""
        import stat as _stat

        full = path if os.path.isabs(path) else os.path.join(
            getattr(self.env, "cwd", None) or self.cwd, path)
        try:
            st = os.stat(full)
        except (FileNotFoundError, NotADirectoryError):
            if os.path.islink(full):  # dangling: an entry, not an absent path (``_probe_regular_file``)
                return self._not_regular_error(path)
            return self._read_file_missing(path, offset, limit)
        except OSError:
            return self._read_file_sequential(path, offset, limit)
        if not _stat.S_ISREG(st.st_mode):
            return self._not_regular_error(path)
        file_size = st.st_size
        if self._is_image(path):
            return self._image_redirect_result(file_size)

        from .limits import get_max_line_length
        clamp = 4 * get_max_line_length() + 1
        end_line = offset + limit - 1

        page: list[bytes] = []
        total_lines = 0
        lineno = 1              # the line currently being scanned
        kept = bytearray()      # first ``clamp`` bytes of that line
        have_partial = False    # that line has bytes but no newline yet
        last_byte = b""
        digest = hashlib.sha256()
        try:
            with open(full, "rb") as fh:
                sample = fh.read(1000)
                ext_binary = has_binary_extension(path)
                if ext_binary or self._is_likely_binary_bytes(sample):
                    return self._read_binary_file(path, offset, limit, file_size, sample)
                fh.seek(0)
                while True:
                    chunk = fh.read(1 << 20)
                    if not chunk:
                        break
                    digest.update(chunk)
                    last_byte = chunk[-1:]
                    if lineno > end_line:
                        # Past the window: only the line count and trailing byte
                        # are needed, so let memchr do it instead of per-line work.
                        total_lines += chunk.count(b"\n")
                        have_partial = chunk[-1:] != b"\n"
                        continue
                    pos, n = 0, len(chunk)
                    while pos < n:
                        nl = chunk.find(b"\n", pos)
                        in_page = offset <= lineno <= end_line
                        if nl < 0:
                            if in_page and len(kept) < clamp:
                                kept += chunk[pos:pos + (clamp - len(kept))]
                            have_partial = True
                            break
                        if in_page:
                            if len(kept) < clamp:
                                kept += chunk[pos:min(nl, pos + (clamp - len(kept)))]
                            page.append(bytes(kept) + b"\n")
                        kept = bytearray()
                        have_partial = False
                        total_lines += 1
                        lineno += 1
                        pos = nl + 1
        except OSError:
            return self._read_file_sequential(path, offset, limit)
        if have_partial and offset <= lineno <= end_line:
            # ``sed`` prints a final line that lacks a newline; ``cut`` adds one.
            page.append(bytes(kept) + b"\n")

        read_output = _strip_terminal_fence_leaks(b"".join(page).decode("utf-8", errors="replace"))
        result = self._assemble_read_result(
            read_output, offset=offset, end_line=end_line, total_lines=total_lines,
            file_size=file_size,
            file_ends_with_newline=(last_byte == b"\n") if file_size else None)
        result._snapshot = (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns, digest.digest())
        return result

    @staticmethod
    def _image_redirect_result(file_size: int) -> ReadResult:
        return ReadResult(
            is_image=True, is_binary=True, file_size=file_size,
            hint=(
                "Image file detected. Automatically redirected to vision_analyze tool. "
                "Use vision_analyze with this file path to inspect the image contents."))

    def _read_file_missing(self, path: str, offset: int, limit: int) -> ReadResult:
        """Not-found recovery shared by every read path. Unicode-equivalent spellings
        (NFC/NFD, confusable spaces/quotes) render identically, so the model can never
        discover the byte mismatch by retyping — retrying is the tool's job. No
        equivalent spelling → suggest similar files."""
        variant = self._unicode_variant_match(path)
        if variant is not None:
            result = self.read_file(variant, offset=offset, limit=limit)
            note = (
                f"Note: '{path}' not found byte-for-byte; resolved to "
                f"the unicode-equivalent file '{variant}' (invisible "
                "encoding difference: NFC/NFD or special space/quote "
                "characters).")
            result.hint = f"{note} {result.hint}" if result.hint else note
            return result
        return self._suggest_similar_files(path)

    def _read_binary_file(self, path: str, offset: int, limit: int,
                          file_size: int, sample_bytes: Optional[bytes]) -> ReadResult:
        """Binary branch shared by every read path: UTF-16 text (Notepad, PowerShell
        ``>``) trips the binary guard; transcode it, else refuse with the type name.

        UTF-16 rescue (ported from MoonshotAI/kimi-code#2647): the terminal env decodes stdout as UTF-8 with
        errors="replace", so a UTF-16 text file (Windows Notepad .txt, PowerShell `>` redirects) arrives
        mangled with U+FFFD and trips the binary guard. Probe the raw bytes via the backend's Python and
        transcode to UTF-8 when a BOM or the zero-byte parity heuristic identifies UTF-16.
        """
        utf16_result = self._try_read_utf16(path, offset, limit, file_size)
        if utf16_result is not None:
            return utf16_result
        return ReadResult(
            is_binary=True, file_size=file_size,
            error=describe_binary_file(sample_bytes, file_size))

    def _assemble_read_result(self, read_output: str, *, offset: int, end_line: int,
                              total_lines: int, file_size: int,
                              file_ends_with_newline: Optional[bool]) -> ReadResult:
        """Turn a raw ``sed | cut`` page into the final ``ReadResult``. Shared by every
        read path so the BOM strip, pagination hint, ``cut`` newline-artifact fix and
        the ambiguous-silence guards never drift apart. ``file_ends_with_newline`` is
        None when the caller could not tell (artifact left alone, as before)."""
        # ``wc -l`` counts newlines, not lines: a nonempty file whose last byte
        # is not a newline holds one more line than the count (#3907). Adjust
        # here — the single choke point — so total_lines, truncation, and the
        # past-EOF guard agree on every read path (compound, sequential, native).
        if file_size > 0 and file_ends_with_newline is False:
            total_lines += 1
        if offset == 1:  # only the first chunk can carry a BOM (byte 0)
            read_output, _ = _strip_bom(read_output)
        truncated = total_lines > end_line
        hint = None
        if truncated:
            hint = f"Use offset={end_line + 1} to continue reading (showing {offset}-{end_line} of {total_lines} lines)"

        # ``cut`` always newline-terminates, so a file without a trailing newline
        # would grow a phantom empty last line; strip it when the last byte says so.
        if not truncated and read_output.endswith('\n') and file_ends_with_newline is False:
            read_output = read_output[:-1]

        # Empty content is indistinguishable from a broken tool: name the dead end.
        if file_size == 0:
            return ReadResult(content="", total_lines=0, file_size=0, hint="File is empty (0 bytes).")
        if offset > total_lines > 0:
            return ReadResult(
                content="", total_lines=total_lines, file_size=file_size,
                hint=(
                    f"Note: offset {offset} is beyond the end of the file "
                    f"({total_lines} lines total). Retry with offset <= "
                    f"{total_lines}."))
        from .limits import get_max_line_length
        max_line_length = get_max_line_length()
        truncated_lines = any(len(line) > max_line_length for line in read_output.split('\n'))
        return ReadResult(
            content=self._add_line_numbers(read_output, offset), total_lines=total_lines,
            file_size=file_size, truncated=truncated, hint=hint,
            truncated_lines=True if truncated_lines else None)

    _CONFUSABLES = (
        ("\u202f", " "),  # narrow no-break space (macOS screenshots)
        ("\u00a0", " "),  # no-break space
        ("\u2019", "'"),  # right single quotation mark (Finder)
        ("\u2018", "'"),  # left single quotation mark
    )

    def _unicode_variant_match(self, path: str) -> Optional[str]:
        """On-disk spelling of a file whose name is unicode-equivalent to ``path``
        (NFC/NFD, confusable spaces/quotes). Returns the entry only when EXACTLY one
        matches — several candidates = homoglyph collision, guessing would read the
        wrong file."""
        dir_path = os.path.dirname(path) or "."
        filename = os.path.basename(path)
        if not filename:
            return None

        def _canon(name: str) -> str:
            out = unicodedata.normalize("NFC", name)
            for src, dst in self._CONFUSABLES:
                out = out.replace(src, dst)
            return out

        target = _canon(filename)
        ls_result = self._exec(f"ls -1 {self._escape_shell_arg(dir_path)} 2>/dev/null")
        if ls_result.exit_code != 0 or not ls_result.stdout.strip():
            return None
        candidates = [
            entry for entry in _strip_terminal_fence_leaks(ls_result.stdout).splitlines()
            if entry and entry != filename and _canon(entry) == target]
        if len(candidates) == 1:
            return os.path.join(dir_path, candidates[0]) if dir_path != "." or "/" in path else candidates[0]
        return None

    def _suggest_similar_files(self, path: str) -> ReadResult:
        """"File not found" result listing up to 5 similar names from the same directory."""
        dir_path = os.path.dirname(path) or "."
        filename = os.path.basename(path)
        basename_no_ext = os.path.splitext(filename)[0].lower()
        ext = os.path.splitext(filename)[1].lower()
        lower_name = filename.lower()
        ls_result = self._exec(f"ls -1 {self._escape_shell_arg(dir_path)} 2>/dev/null | head -50")
        scored: list = []  # (score, filepath) — higher is better
        if ls_result.exit_code == 0 and ls_result.stdout.strip():
            for f in ls_result.stdout.strip().split('\n'):
                if not f:
                    continue
                lf = f.lower()
                score = 0
                if lf == lower_name:
                    score = 100
                elif os.path.splitext(f)[0].lower() == basename_no_ext:  # config.yml vs config.yaml
                    score = 90
                elif lf.startswith(lower_name) or lower_name.startswith(lf):
                    score = 70
                elif lower_name in lf:
                    score = 60
                elif lf in lower_name and len(lf) > 2:
                    score = 40
                elif ext and os.path.splitext(f)[1].lower() == ext:
                    common = set(lower_name) & set(lf)
                    if len(common) >= max(len(lower_name), len(lf)) * 0.4:
                        score = 30
                # Near-miss spelling (AGENT.md -> AGENTS.md) the substring checks miss.
                if score == 0 and difflib.SequenceMatcher(None, lower_name, lf).ratio() >= 0.8:
                    score = 50
                if score > 0:
                    scored.append((score, os.path.join(dir_path, f)))
        scored.sort(key=lambda x: -x[0])
        return ReadResult(error=f"File not found: {path}", not_found=True,
                          similar_files=[fp for _, fp in scored[:5]])

    def _no_match_result(self, path: str, content: str, old_string: str,
                         new_string: str, match_count: int, error: Optional[str]) -> PatchResult:
        """PatchResult for a failed fuzzy match. Already-applied detection first: the
        most common production failure is a re-send of an edit that already landed,
        and a success-shaped no-op stops the model burning turns on re-reads.
        Otherwise attach a best-effort "Did you mean?" snippet to the error."""
        from .fuzzy_match import format_no_match_hint, is_already_applied
        if is_already_applied(content, old_string, new_string):
            return PatchResult(
                success=True, no_change=True,
                note=(
                    f"File already contains the target text — the edit "
                    f"appears to be already applied to {path}. No write "
                    "performed; do not re-send this patch."))
        err_msg = error or f"Could not find match for old_string in {path}"
        try:
            err_msg += format_no_match_hint(err_msg, match_count, old_string, content)
        except Exception:
            pass
        return PatchResult(error=err_msg)
