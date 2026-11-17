"""Private bootstrap; native imports must come from the selected Snapshot."""

import json
import os
import shutil
import sys
from pathlib import Path


def main():
    files = Path(sys.argv.pop(1))
    sys.path.insert(0, str(files / "runtime"))
    # Init uses native template/layout handling without interactive setup. Keep
    # stdout exclusively for the native SDK protocol, including during imports.
    with os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8") as protocol:
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
        try:
            # Both packages are candidate code. Never silently use an installed
            # baseline when a candidate removes its package initializer.
            for name in ("jiuwenswarm", "openjiuwen"):
                package = files / "runtime" / name
                if not (package / "__init__.py").is_file():
                    raise ValueError(f"Snapshot must contain native {name} source")
                module = __import__(name)
                if (
                    Path(module.__file__).resolve()
                    != (package / "__init__.py").resolve()
                ):
                    raise ValueError(f"{name} was imported outside the Snapshot")
            from jiuwenswarm.common.utils import (
                get_agent_skills_dir,
                get_user_workspace_dir,
                prepare_workspace,
            )

            prepare_workspace(
                overwrite=False,
                workspace_dir=get_user_workspace_dir(),
                migrate_config=False,
            )
            if (files / "skills").is_dir():
                shutil.copytree(
                    files / "skills", get_agent_skills_dir(), dirs_exist_ok=True
                )
            from jiuwenswarm.channels.process_cli.main import main as native_main

        except Exception as error:
            # Preserve initialization errors in the native result envelope.
            request = json.loads(sys.stdin.readline())
            print(
                json.dumps(
                    {
                        "schema_version": "0.1",
                        "type": "result",
                        "sequence": 0,
                        "request_id": request["request_id"],
                        "session_id": None,
                        "status": "failed",
                        "exit_code": 1,
                        "output": "",
                        "usage": {},
                        "error": {
                            "code": "BOOTSTRAP_FAILED",
                            "message": f"{type(error).__name__}: {error}",
                        },
                    }
                ),
                file=protocol,
                flush=True,
            )
            raise SystemExit(1)
        sys.stdout.flush()
        os.dup2(protocol.fileno(), sys.stdout.fileno())
        native_main()


if __name__ == "__main__":
    main()
