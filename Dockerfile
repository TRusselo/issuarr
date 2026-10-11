# syntax=docker/dockerfile:1

# Drop-in replacement for lscr.io/linuxserver/mylar3 built from this checkout.
# Based on linuxserver/docker-mylar3 (GPL-3.0): same s6 base image, PUID/PGID/UMASK/TZ
# handling, /config/mylar data dir and port 8090.

FROM ghcr.io/linuxserver/unrar:latest AS unrar

FROM ghcr.io/linuxserver/baseimage-ubuntu:jammy

ARG BUILD_DATE
ARG VERSION
ARG MYLAR3_BRANCH=main
ARG MYLAR3_COMMIT=unknown
LABEL build_version="TRusselo/Issuarr version:- ${VERSION} Build-date:- ${BUILD_DATE}"
LABEL org.opencontainers.image.source="https://github.com/TRusselo/Issuarr"

COPY requirements.txt /tmp/requirements.txt

RUN \
  echo "**** install build dependencies ****" && \
  apt-get update && \
  apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    libjpeg9-dev \
    libwebp-dev \
    python3-dev \
    zlib1g-dev && \
  echo "**** install runtime packages ****" && \
  apt-get install -y --no-install-recommends \
    libjpeg9 \
    nodejs \
    python3-venv \
    webp \
    zlib1g && \
  echo "**** install python requirements ****" && \
  python3 -m venv /lsiopy && \
  pip install -U --no-cache-dir \
    pip \
    setuptools \
    wheel && \
  pip install --no-cache-dir --find-links https://wheel-index.linuxserver.io/ubuntu/ -r /tmp/requirements.txt && \
  echo "**** cleanup ****" && \
  apt-get -y purge \
    build-essential \
    libffi-dev \
    libjpeg9-dev \
    libwebp-dev \
    python3-dev \
    zlib1g-dev && \
  apt-get -y autoremove && \
  rm -rf \
    /tmp/* \
    /var/lib/apt/lists/* \
    /var/tmp/* \
    $HOME/.cache

# add mylar
COPY . /app/mylar3/
RUN \
  printf " (%s)\n%s\n" "${MYLAR3_BRANCH}" "${MYLAR3_COMMIT}" > /app/mylar3/.LAST_RELEASE && \
  rm -rf /app/mylar3/docker && \
  printf "TRusselo/Issuarr version: ${VERSION}\nBuild-date: ${BUILD_DATE}" > /build_version

# add local files
COPY docker/root/ /

# add unrar
COPY --from=unrar /usr/bin/unrar-ubuntu /usr/bin/unrar

# ports and volumes
VOLUME /config
EXPOSE 8090
