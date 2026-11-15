# Runtime qualification image. Install the .deb and its declared dependencies
# during the test, rather than inheriting the builder's development libraries.
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
      xvfb xauth xdotool openbox procps dbus-x11 desktop-file-utils curl jq ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /qualification
