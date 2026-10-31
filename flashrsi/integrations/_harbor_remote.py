"""Harbor 0.23 Docker transport when the daemon cannot see host log paths."""

import json
from pathlib import PurePosixPath

from harbor.environments.docker.docker import DockerEnvironment


class _RemoteDockerEnvironment(DockerEnvironment):
    @property
    def capabilities(self):
        # Trial downloads logs via Harbor's existing copy transport.
        return super().capabilities.model_copy(update={"mounted": False})

    def _write_mounts_compose_file(self):
        # Task-defined volumes require their own synchronization semantics.
        # Refuse them rather than silently dropping inputs or isolation rules.
        if self._is_windows_container or self._uses_compose:
            raise ValueError("Remote Docker supports single-service Linux tasks only")
        for mount in self._mounts:
            target = PurePosixPath(mount.get("target", ""))
            if (
                mount.get("type") != "bind"
                or mount.get("read_only")
                or ".." in target.parts
                or not target.is_relative_to("/logs")
                or target == PurePosixPath("/logs")
            ):
                raise ValueError(
                    "Remote Docker supports only writable log mounts under /logs"
                )
        path = super()._write_mounts_compose_file()
        path.write_text(json.dumps({"services": {"main": {"volumes": []}}}))
        # Keep self._mounts: start() uses their targets to create log directories.
        return path
