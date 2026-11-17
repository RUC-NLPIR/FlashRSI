FROM python:3.12-slim AS build
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources && apt-get -o Acquire::Retries=3 update && apt-get -o Acquire::Retries=3 install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN pip wheel --no-deps -w /wheels \
    'git+https://github.com/openJiuwen-ai/jiuwenswarm.git@09b3b6b7f3fa7808625dc2803b1aede5125bdb8c' \
    'git+https://gitcode.com/openJiuwen/agent-core.git@f3f8f576164cc405c046e43079c8ad00ee17f0c4' \
    'git+https://gitcode.com/openJiuwen/agent-protocol.git@4c5f3e9eb41bd33d34d012b06a3e364e8497ac11#subdirectory=openjiuwen-protocol' \
    'git+https://gitcode.com/openJiuwen/agent-protocol.git@1699ea352a08430731c6dddac0fc46a1b1a385f2#subdirectory=A4P' \
    'git+https://gitcode.com/openJiuwen/agent-gateway.git@435d3323425e1051c6fe2d1feadcba68b4be020d' \
    'git+https://gitcode.com/openJiuwen/computer-use.git@96afb268c4c9f835dd1b2300b876d13dd93c982b' \
    'git+https://gitcode.com/openJiuwen/agent-runtime.git@7d31f51c398da760de72c66cf2b9a78265cc2af2#subdirectory=foundation'

FROM scratch
COPY --from=build /wheels/ /
