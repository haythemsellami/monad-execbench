FROM ubuntu:26.04@sha256:2260313b31c8c011cd2eebe728008efac1b3982be73eb71348ea2648d2c0e09b

ENV DEBIAN_FRONTEND=noninteractive
# Apt patch revisions can change; this is a repeatable supported environment,
# not a bit-reproducible build. System libraries follow the pinned Monad source.
COPY third_party/monad/scripts/ubuntu-build/install-boost.sh /opt/install-boost.sh
COPY third_party/monad/scripts/ubuntu-build/install-deps.sh /opt/install-deps.sh
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ca-certificates cmake curl g++-15 gcc-15 git ninja-build pkg-config python3-venv && \
    bash /opt/install-boost.sh && bash /opt/install-deps.sh && \
    apt-get clean

ENV PATH="/opt/foundry:/work/.venv/bin:${PATH}"
ARG EXECBENCH_UID=1000
ARG EXECBENCH_GID=1000
RUN if ! getent group "${EXECBENCH_GID}"; then groupadd --gid "${EXECBENCH_GID}" execbench; fi && \
    useradd --non-unique --uid "${EXECBENCH_UID}" --gid "${EXECBENCH_GID}" \
      --create-home --home-dir /home/execbench execbench
USER execbench
WORKDIR /work
