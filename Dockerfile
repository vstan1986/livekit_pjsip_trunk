# =============================================================================
# Stage 1: Builder — compile PJSIP 2.15.1 + Python SWIG bindings
# =============================================================================
FROM python:3.9-slim AS builder

WORKDIR /opt

# Prevent interactive prompts during apt
ENV DEBIAN_FRONTEND=noninteractive

# Install build dependencies + wget for downloading PJSIP
RUN apt update && \
    apt install --fix-missing -y \
        build-essential \
        python3-dev \
        swig \
        libssl-dev \
        libncurses5-dev \
        uuid-dev \
        libltdl-dev \
        pkg-config \
        wget \
        && \
    wget -q https://github.com/pjsip/pjproject/archive/refs/tags/2.15.1.tar.gz \
      -O /opt/pjproject-2.15.1.tar.gz && \
    apt clean && \
    rm -rf /var/lib/apt/lists/*

# Extract the archive
RUN tar xzf /opt/pjproject-2.15.1.tar.gz -C /opt && \
    rm -f /opt/pjproject-2.15.1.tar.gz

# Build PJSIP
WORKDIR /opt/pjproject-2.15.1

# Configure with media subsystems disabled (no ALSA, PulseAudio, video, etc.)
# We only need basic SIP signalling + Opus codec passthrough
RUN export CFLAGS="$CFLAGS -fPIC -O2" && \
    ./configure \
        --enable-shared \
        --disable-alsa \
        --disable-pa \
        --disable-opencore-amr \
        --disable-silk \
        --disable-sdl \
        --disable-v4l2 \
        --disable-ffmpeg \
        --disable-video \
        --disable-libyuv \
        --disable-libwebrtc \
        --disable-speex-aec \
        --disable-l16-codec \
        --disable-gsm-codec \
        --disable-speex-codec \
        --disable-g722-codec \
        --disable-g7221-codec \
        --disable-ilbc-codec \
        && \
    make dep && \
    make -j"$(nproc)" && \
    make install

# Build and install Python SWIG module (pjsua2)
WORKDIR /opt/pjproject-2.15.1/pjsip-apps/src/swig/python
RUN make && \
    make install && \
    python3 setup.py install

# Strip debugging symbols to reduce size
RUN find /usr/local/lib -name "*.so*" -exec strip --strip-unneeded {} \; 2>/dev/null || true

# Clean source tree
WORKDIR /opt
RUN rm -rf /opt/pjproject-2.15.1


# =============================================================================
# Stage 2: Runner — minimal runtime image
# =============================================================================
FROM python:3.9-slim

WORKDIR /app

# Install runtime dependencies
RUN apt update && \
    apt install --no-install-recommends -y \
        ca-certificates \
        && \
    apt clean && \
    rm -rf /var/lib/apt/lists/*

# Copy PJSIP libraries from builder
COPY --from=builder /usr/local/lib /usr/local/lib

# Copy the Python SWIG module
COPY --from=builder /usr/local/lib/python3.9/site-packages /usr/local/lib/python3.9/site-packages

# Update linker cache
RUN ldconfig

# Copy application files
COPY gateway.py /app/
COPY config.py /app/
COPY sip_helpers.py /app/
COPY health.py /app/
COPY config.json /app/

# Health check
EXPOSE 8080

# SIP signalling ports — one per line (register_port + listen_port)
# Examples (used in provided config.json):
#   Line 1: register_port=5061  listen_port=5062
#   Line 2: register_port=5063  listen_port=5064
# ⚠ If you change ports in config.json, update EXPOSE and docker-compose.yml
EXPOSE 5061/udp 5062/udp 5063/udp 5064/udp

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

# Run gateway
CMD ["python3", "-u", "gateway.py"]
