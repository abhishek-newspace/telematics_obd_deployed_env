FROM debian:bookworm AS production

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgtk-3-0 \
    libglib2.0-0 \
    libstdc++6 \
    libx11-6 \
    libasound2 \
    libwayland-client0 \
    libwayland-cursor0 \
    libwayland-egl1 \
    libegl1 \
    libgles2 \
    libgl1 \
    libgl1-mesa-dri \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m appuser

WORKDIR /app

COPY ./bundle/ .

RUN chmod +x ./scout_display

# Host session uses X11 (DISPLAY=:0). Wayland fails inside Docker.
ENV GDK_BACKEND=x11

RUN chown -R appuser:appuser /app
USER appuser

CMD ["./scout_display", "fullscreen"]
