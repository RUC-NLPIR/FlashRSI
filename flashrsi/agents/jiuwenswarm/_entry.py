"""Private bootstrap; native imports must come from the selected Snapshot."""

import json
import os
import shutil
import sys
from importlib.metadata import version
from importlib.util import spec_from_file_location
from pathlib import Path


class _SingleAgentModules:
    """Load the editable modules before their installed parent packages import them."""

    def __init__(self, runtime: Path):
        self.paths = {}
        for name in (
            "jiuwenswarm.agents.harness.common.prompt.prompt_builder",
            "openjiuwen.core.single_agent.agents.react_agent",
        ):
            source = runtime.joinpath(*name.split(".")).with_suffix(".py")
            if not source.is_file():
                raise ValueError(f"Snapshot is missing {source.relative_to(runtime)}")
            self.paths[name] = source

    def find_spec(self, fullname, path=None, target=None):
        if fullname in self.paths:
            return spec_from_file_location(fullname, self.paths[fullname])
        return None


def main():
    files = Path(sys.argv.pop(1))
    runtime = files / "runtime"
    # Init uses native template/layout handling without interactive setup. Keep
    # stdout exclusively for the native SDK protocol, including during imports.
    with os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8") as protocol:
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
        try:
            # Earlier Snapshots carried complete packages and resolve all imports
            # from those trees. New seeds override just the two single-agent modules.
            if any(
                (runtime / name / "__init__.py").is_file()
                for name in ("jiuwenswarm", "openjiuwen")
            ):
                sys.path.insert(0, str(runtime))
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
            else:
                for package, expected in (
                    ("workswarm", "0.2.8"),
                    ("openjiuwen", "0.1.20"),
                ):
                    if version(package) != expected:
                        raise ValueError(f"JiuwenSwarm requires {package}=={expected}")
                sys.meta_path.insert(0, _SingleAgentModules(runtime))
                # Native modules may import candidate-authored jiuwen_extensions helpers.
                sys.path.append(str(runtime))
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
