# Runtime qualification image. Build tools and system Python are omitted.
FROM archlinux:base
RUN pacman -Syu --noconfirm \
      gtk3 webkit2gtk-4.1 xorg-server-xvfb xdotool openbox procps-ng \
      dbus desktop-file-utils curl jq diffutils \
    && pacman -Scc --noconfirm
WORKDIR /qualification
