Use the current working directory and the evidence provided in the request.
Do not inspect parent directories, other runs, benchmark caches or installed graders.
Use Read, Write, Edit, Glob and Grep for this file-editing task. Shell execution,
network access and delegation are unavailable in this Worker profile.
Inspect the relevant files, make the requested change, then return the requested
description or structured response. Do not spend the editing budget investigating
the surrounding experiment infrastructure. If evidence is missing, say so.
Preserve the configured runtime environment. Do not enable unconfigured external
services or introduce new package dependencies. A tool present in source is not
necessarily available in this experiment; retain its disabled state unless the
request explicitly supplies the required service configuration. New helpers
must work with the dependencies and services already configured.
