"""Original binary/document write guard, bound to the task-local filesystem."""
import os
from pathlib import Path
from .binary_extensions import has_binary_extension, has_opaque_document_extension, is_pdf_path, is_sqlite_sidecar

def _target_regular_file_state(filepath, task_id):
    path = Path(filepath).expanduser()
    if not path.is_absolute():
        path = Path(task_id) / path
    try:
        return "exists" if path.is_file() else "missing"
    except OSError:
        return "unavailable"

def _check_binary_document_write(filepath: str, task_id: str = "default") -> str | None:
    """Reject text-tool writes that would corrupt a binary document (read_file showed
    EXTRACTED text, so the model may write it back). Opaque document formats and
    SQLite sidecars (-wal/-shm/-journal) are always rejected; .pdf and every other
    BINARY_EXTENSIONS suffix only when OVERWRITING an existing file (raw PDF syntax
    is text-authorable and text fixtures named ``*.db`` exist). "Existing" is asked
    of the filesystem the write will hit — the task's backend, via
    ``_target_regular_file_state`` — never the controller's disk alone (#122662).

    ``read_file`` auto-extracts .docx/.xlsx/.pptx (and PDF, via anydoc) to readable text, so the model
    plausibly believes it holds the file's contents and tries to write the edited text back with
    write_file/patch. A plain-text write can never produce a valid OOXML/OLE/ODF container, so that write
    silently destroys the document (port of nearai/ironclaw#7109).
    """
    ext = os.path.splitext(filepath)[1].lower()
    if has_opaque_document_extension(filepath):
        return (
            f"Refusing to write plain text to binary document '{filepath}' ({ext}). "
            "A text write cannot produce a valid document container and would "
            "corrupt the file (read_file showed you EXTRACTED text, not the real "
            "bytes). Use the docx/xlsx/powerpoint skills or a library like "
            "python-docx/openpyxl/python-pptx via the terminal to create or edit "
            "this document.")
    # A -wal/-shm/-journal path is never a legitimate text target, even when
    # no sidecar exists yet: a checkpointed db has none on disk, and a garbage
    # WAL dropped next to a live database is picked up on the next open.
    if is_sqlite_sidecar(filepath):
        return (
            f"Refusing to write plain text to binary SQLite sidecar '{filepath}' ({ext}). "
            "A -wal/-shm/-journal file holds raw database pages that SQLite "
            "reads on the next open; text there corrupts the database. Use the "
            "sqlite3 CLI or a SQLite library via the terminal to modify the "
            "database instead.")
    # Overwriting an existing binary (PDF, image, archive, SQLite db, ...)
    # with text destroys it — the model only ever saw extracted or mojibake
    # text. Creating a NEW file with such an extension stays allowed: raw PDF
    # syntax is text-authorable and text fixtures named ``*.db`` exist.
    pdf = is_pdf_path(filepath)
    if pdf or has_binary_extension(filepath):
        state = _target_regular_file_state(filepath, task_id)
        if state == "exists":
            if pdf:
                return (
                    f"Refusing to overwrite existing PDF '{filepath}' with plain text. "
                    "read_file showed you EXTRACTED text, not the real bytes — writing "
                    "text back would destroy the document. Use the pdf skill or a PDF "
                    "library via the terminal to modify it. (Creating a NEW .pdf file "
                    "is allowed.)")
            return (
                f"Refusing to overwrite existing binary file '{filepath}' ({ext}) "
                "with plain text — read_file showed you extracted or mojibake "
                "text, not the real bytes, and writing text back would destroy "
                "the file. Use a binary-aware tool via the terminal to modify it "
                "(for SQLite databases, the sqlite3 CLI or a SQLite library). "
                "(Creating a NEW file with this extension is allowed.)")
        if state == "unavailable":
            # Fail closed: absence not proven on the filesystem the write would
            # hit, so proceeding could destroy a binary the guard never saw.
            return (
                f"Refusing to write to '{filepath}': could not establish whether "
                "the target file already exists where this write would execute "
                "(the terminal environment may be starting, unreachable, or was "
                "removed). The file was NOT modified — retry once the environment "
                "is reachable.")
    return None
