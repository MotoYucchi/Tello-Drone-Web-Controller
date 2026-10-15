# Tello Drone Web Controller

A web-based DJI Tello drone controller with explicit WiFi interface binding, LineTrace (LSD line segment detection), and late-2010s dark-mode UI.

---

## Table of Contents

- [Overview](#overview)
- [Design Principles & Key Features](#design-principles--key-features)
- [Feature Matrix](#feature-matrix)
- [Requirements](#requirements)
- [Setup Guide](#setup-guide)
- [Starting the Application](#starting-the-application)
- [Usage & Controls](#usage--controls)
  - [1. Connecting to Tello](#1-connecting-to-tello)
  - [2. Flight Controls (Buttons & Keyboard)](#2-flight-controls-buttons--keyboard)
  - [3. Smartphone & Tablet Controls](#3-smartphone--tablet-controls)
  - [4. LineTrace (LSD Auto-Follow)](#4-linetrace-lsd-auto-follow)
  - [5. Video Streaming & Latency Compensation](#5-video-streaming--latency-compensation)
  - [6. Screenshot Capture (PNG Download)](#6-screenshot-capture-png-download)
  - [7. Experimental Features (Square Course & 10Hz Logging)](#7-experimental-features-square-course--10hz-logging)
  - [8. Flight Logging (Timeline CSV)](#8-flight-logging-timeline-csv)
  - [9. QR Code Detection](#9-qr-code-detection)
- [Smartphone Usage Notes (HTTP Security Policy Constraints)](#smartphone-usage-notes-http-security-policy-constraints)
- [Network Architecture](#network-architecture)
- [API Reference](#api-reference)
- [Troubleshooting](#troubleshooting)
- [Project Structure](#project-structure)
- [Safety Notice & Disclaimer](#safety-notice--disclaimer)
- [License](#license)

---

## Overview

This project is an open-source web controller designed for operating and experimenting with DJI Tello (and Tello EDU) drones via a modern web browser. It is built on FastAPI, raw UDP socket networking, WebSocket duplex messaging, and OpenCV (LineSegmentDetector and HSV color-space processing).

It addresses practical challenges such as packet routing on dual-network machines (Ethernet internet + Tello WiFi multihoming) and provides responsive controls on both desktop and mobile devices.

---

## Design Principles & Key Features

1. **Explicit WiFi Socket Binding**:
   When your PC is connected to both wired Ethernet and Tello's wireless network (`192.168.10.x`), operating system routing tables can route UDP packets inappropriately. This application binds raw UDP sockets directly to the specified wireless adapter IP for commands (`8889`), telemetry (`8890`), and video streaming (`11111`).
2. **LineTrace Algorithm (OpenCV LSD + Preprocessing)**:
   Employs Gaussian blur filtering, HSV mask thresholding, morphological closing/opening, and `cv2.createLineSegmentDetector` (LSD) to detect floor track line segments. Supports two physical airframe configurations:
   - **Standard Drone**: Forward-tilted camera, controlled primarily via Yaw rotation and forward speed.
   - **Modified Drone**: Downward-facing camera, controlled via lateral Roll translation and forward speed.
3. **Late-2010s Dark UI & Responsive Layout**:
   Features a functional, eye-friendly dark gray interface (inspired by classic VS Code and GitHub Dark themes) without heavy blurs or distracting neon glow effects. Includes a virtual on-screen D-Pad for touchscreens.
4. **Timeline CSV Logging & Still Capture**:
   Automatically records flight metrics (timestamp, battery, altitude, temperature, attitude Euler angles, velocities, RC stick values, and LineTrace status) at 1-second intervals (or 10Hz when experimental features are enabled). The latest video frame can be saved directly as a PNG file.

---

## Feature Matrix

| Category | Feature | Description |
|---|---|---|
| **Networking** | Interface Selection | Auto-detection or explicit local IP socket binding |
| | Telemetry Stream | Real-time battery, altitude, temperature, and flight time |
| | Connection Management | Clean socket closure and reconnection handling without restarting |
| **Flight Control** | Takeoff / Land / Emergency | GUI buttons, keyboard shortcuts, or virtual touch buttons |
| | Manual Piloting | WASD (Pitch/Roll), R/F (Throttle), Q/E (Yaw) |
| | Touch D-Pad | Virtual controller on touchscreen devices (hold to move, release to hover) |
| **Video & Media** | Low-latency MJPEG | Live video stream with quality presets (low/medium/high) |
| | PNG Screenshot | Download latest video frame (`TELLO_YYYY-MM-DD-HH-mm-ss.png`) |
| | LineTrace HUD Overlay | Real-time visualization of detected segments and heading vectors |
| | Latency Reset & Mode | Manual buffer flush and latency mode configuration |
| **Line Tracking** | LSD Line Detection | Line segment extraction via OpenCV LSD |
| | Dual Camera Modes | Standard (Yaw-based) vs. Downward-facing (Roll-based) control |
| | Failsafe Actions | Instant hovering on line loss, speed reduction on 90-degree corners |
| | Corner Forward Speed Control | Configurable forward speed during cornering (1-100) |
| | Corner Memory & Recovery | Turn direction retention (up to 20s), backtrack reverse (speed up to 48), 360° auto-rotate search |
| | Square Course Lap Tracking (Experimental) | Automatic lap count and lap timer based on 4 detected corners with HUD overlay |
| **Data & Tools** | Flight Logging | CSV timeline export per flight session (1Hz standard / 10Hz experimental) |
| | QR Code Scanner | Text/URL recognition from video stream with CSV export |

---

## Requirements

| Component | Requirement |
|---|---|
| **Operating System** | Windows 10 / 11, macOS, Linux |
| **Python** | 3.11+ (tested on 3.12, 3.13, 3.14) |
| **Package Manager** | [uv](https://docs.astral.sh/uv/) (recommended) or pip |
| **Target Drone** | DJI Tello / Tello EDU (standard firmware) |
| **Web Browser** | Google Chrome, Microsoft Edge, Mozilla Firefox, Safari (latest) |

---

## Setup Guide

### Quick Setup (Recommended)

Launcher scripts are provided for automatic dependency installation and startup:

**Windows:**
```bat
start.bat
```

**macOS / Linux:**
```bash
chmod +x start.sh
./start.sh
```

---

### Manual Setup

#### 1. Install uv (if not already installed)

- **Windows (PowerShell):**
  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```
- **macOS / Linux:**
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

#### 2. Install Project Dependencies

```bash
cd Tello-Drone-Web-Controller
uv sync
```

#### 3. Start the Server

```bash
uv run python -m src
```

Open `http://localhost:8000` in your browser (or `http://<PC_IP>:8000` from mobile devices on the same network).

---

## Starting the Application

```bash
# Start server
uv run python -m src

# Run test suite (38 automated test cases)
uv run pytest -v
```

---

## Usage & Controls

### 1. Connecting to Tello

1. Power on the drone and wait until the front LED blinks yellow.
2. Connect your PC's Wi-Fi to Tello's access point (e.g., `TELLO-XXXXXX`).
3. Open the web interface in your browser.
4. If using Ethernet simultaneously, select the network adapter marked with `★Tello` (usually `192.168.10.x`) in the Network Settings panel.
5. Click **Connect** in the header. Once the status dot turns green, the system is ready.

---

### 2. Flight Controls (Buttons & Keyboard)

| Action | UI Button | Keyboard Key | Description |
|---|---|---|---|
| Takeoff | "Takeoff" | `T` | Ascends to ~1m height and hovers |
| Land | "Land" | `L` | Descends steadily and cuts motors upon ground contact |
| Emergency Stop | "Emergency" | `Space` | Cuts motor power immediately (drone will drop) |
| Forward / Backward | On-screen | `W` / `S` | Pitch control (active while pressed) |
| Left / Right | On-screen | `A` / `D` | Roll control (active while pressed) |
| Ascend / Descend | On-screen | `R` / `F` | Throttle control (active while pressed) |
| Rotate Left / Right | On-screen | `Q` / `E` | Yaw rotation (active while pressed) |

> **Note**: Keyboard shortcuts are automatically suspended when focus is inside a form text input.

---

### 3. Smartphone & Tablet Controls

When accessing the web app from a touchscreen device over the local network:

- **Virtual Touch D-Pad**:
  - Left Pad: Altitude (`R`/`F`) and Yaw Rotation (`Q`/`E`)
  - Right Pad: Pitch (`W`/`S`) and Roll (`A`/`D`)
  - Center: Takeoff (`T`), Land (`L`), and Emergency Stop (`Space`)
- **Interaction**:
  - Movement commands are transmitted continuously while holding down a virtual button. Releasing your finger immediately sends zero-RC commands to return the drone to a neutral hover.
- **Mobile Tabs**:
  - On screens narrower than 768px, a tab bar allows switching between LineTrace, Flight Controls, QR Scanner, and Network panels without endless vertical scrolling.

---

### 4. LineTrace (LSD Auto-Follow)

1. Start video streaming.
2. Position the drone so that the floor line is visible in the frame.
3. Select your **Drone Camera Type**:
   - **Standard Drone (Forward tilt)**: Uses Yaw rotation and forward speed to align with the detected line.
   - **Modified Drone (Downward-facing)**: Uses lateral Roll translation and forward speed to follow the line.
4. Select a color preset (Red, Blue, Yellow, or Black) or fine-tune HSV sliders.
5. Toggle **LineTrace Display** to view detected line segments and heading vectors on the video stream.
6. Toggle **LineTrace Control** to enable autonomous tracking.

#### Stabilization and Safety Features (Failsafe & Auto-Recovery)
- **Anti-Wobble Stabilization**:
  - **Smooth Deadzone Ramp**: Eliminates abrupt torque jumps at deadband boundaries, ensuring gentle transitions.
  - **PD Damping Brake**: Detects approach velocity toward center and applies reverse damping torque ($\frac{d(dx)}{dt}$) to counter rotational inertia and suppress overshoot oscillation.
  - **EMA Smoothing Filter**: Applies Exponential Moving Average to yaw/roll control values, attenuating high-frequency vision noise for steady flight.
  - **Turn & Deviation Deceleration**: Automatically reduces forward speed during tight turns or significant offset to prevent running off the track.
  - **Corner Forward Speed Control (1-100)**: Configure the forward speed during corner turns (`corner_forward_speed`) manually via UI slider or API (range 1-100), tailoring cornering momentum to battery and thrust conditions.
- **Auto-Recovery State Machine (Line Lost)**:
  - **Corner Memory**: For standard drones, if a 90° corner or sharp turn is overshot, the system retains the detected turn direction (right or left) for a configurable duration (default 10s, adjustable 1-20s via UI slider) to guide backtrack recovery and scanning directions if the line is lost.
  - **Phase 1 (0.0s - 0.4s) Inertia Stabilization**: Sets forward speed to 0 and commands neutral hover to cancel forward momentum.
  - **Phase 2 (0.4s - 3.5s) Backtrack Recovery & Scan**:
    - **Standard Drone (Forward tilt)**: If a corner was recently detected, executes reverse flight (speed up to 48, configurable via UI) while yawing toward the remembered direction to pull the overshot line back into the camera FOV. With the "Backtrack on Lost" option enabled, reverse flight is also executed on straight/curved line loss to retrace back to the last known position.
    - **Modified Drone (Downward-facing)**: Scans using lateral roll translation and yaw rotation.
  - **Phase 3 (3.5s - 5.5s) Continuous Search**: Continues searching in the corner direction or reverses scan direction.
  - **Phase 4 (>5.5s) Safe Hover Standby / Auto-Rotate**:
    - **Auto-Rotate while Hovering (Option)**: When enabled, continues a gentle 360-degree yaw rotation while hovering to search for lines in all directions.
    - **Default**: Maintains stationary neutral hover in place if the line is not found.
  - **Autonomous Resumption**: Once the line reappears in the camera frame, tracking resumes automatically (forward speed strictly remains <= 0 during recovery scanning to prevent collisions).

---

### 5. Video Streaming & Latency Compensation

- **Decoupled Capture Architecture**: Video frame capture and compute-heavy processing (LSD, QR detection) run in separate worker threads, mitigating buffer bloat in OpenCV/FFmpeg.
- **Buffer Flush ("Reset Latency" Button)**: Flushes accumulated network frames on demand without needing to restart the video stream.
- **Latency Optimization Modes**:
  - `Normal (30fps)`: Prioritizes smooth playback.
  - `Low Latency (Latest frame)`: Discards delayed frames to maintain lower latency.
  - `Ultra Low (Drop-on-read)`: Drops stale packets on every read loop for minimal display latency.

---

### 6. Screenshot Capture (PNG Download)

- Click the camera button below the video stream to save the current frame.
- Output file format: `TELLO_YYYY-MM-DD-HH-mm-ss.png`
- Captured via backend API (`/api/screenshot`) with Canvas fallback.

---

### 7. Experimental Features (Square Course & 10Hz Logging)

Enable the **"🧪 Experimental Features"** toggle in the top header to unlock additional experimental capabilities:

- **Square Course Lap Counting**:
  - Selecting "Square Course (4 Corners)" in the LineTrace panel tracks the drone's progression around a 4-corner rectangular loop.
  - The video HUD displays `[SQUARE] Lap: 0 (C:0/4) Time: 0.0s`, incrementing laps on every 4 detected turns.
  - Reset lap counters and lap times at any time via the "Reset Laps" button (or `/api/linetrace/reset_laps`).
- **High-Frequency Flight Logging (10Hz CSV)**:
  - When experimental mode is active, flight telemetry is recorded at **10Hz (10 samples/sec)** instead of the standard 1Hz. This enables fine-grained tracking error (`lt_offset_dx`) and cornering dynamics analysis.

---

### 8. Flight Logging (Timeline CSV)

- Every flight session is recorded into a timestamped CSV file in the `logs/` directory (1Hz standard / 10Hz when experimental features are enabled).
- Click **Flight Log CSV** in the Flight Control panel to download the latest session (`logs/TELLO_YYYY-MM-DD-HH-mm-ss.csv`).
- **Logged Columns**: Timestamp, flight time, battery, altitude, temperature, Euler angles (pitch, roll, yaw), velocities (vx, vy, vz), transmitted RC stick values (lr, fb, ud, yaw), flight mode, LineTrace detection status, course type and lap metrics (when in square course mode), and control parameters.

---

### 9. QR Code Detection

- Scans the camera video stream for QR codes, displaying decoded content and URLs.
- Supports storing Student ID / Username and exporting records as CSV.

---

## Smartphone Usage Notes (HTTP Security Policy Constraints)

When accessing this controller from a smartphone or tablet connected to the PC host via local Wi-Fi, the connection URL is `http://<PC_IP>:8000`. Browsers classify this as a **Non-Secure Context (unencrypted HTTP)**.

Please note the following technical constraints enforced by modern mobile browsers (iOS Safari, Android Chrome):

1. **Clipboard API (`navigator.clipboard.writeText`)**:
   - Disabled on plain HTTP. This application provides a legacy `document.execCommand('copy')` fallback and manual copy prompts so scripts will not crash.
2. **Device Sensors (`DeviceOrientation` / Gyroscope)**:
   - Tilt-based device steering is restricted over HTTP. Consequently, this app utilizes **on-screen touch D-Pad buttons** using standard pointer events, which work reliably in HTTP environments.
3. **Push Notifications / Fullscreen APIs**:
   - Certain browser features are restricted. However, standard MJPEG video streaming and WebSocket communication (`ws://`) function properly over local HTTP.
4. **Safety Practice**:
   - Even when piloting from a mobile device, keep the host PC visible so that the physical `Space` key can be pressed immediately for an emergency stop if network latency occurs.

---

## Network Architecture

```
┌───────────────────────────────┐
│              PC               │
│                               │
│  FastAPI Web Controller       │
│  HTTP :8000 / WS :8000        │
│                               │
│  [WiFi Adapter: 192.168.10.x] │
└──────┬─────────────────▲──────┘
       │                 │
       │ UDP :8889 (cmd) │ UDP :8890 (state) / :11111 (video)
       │                 │
┌──────▼─────────────────┴──────┐
│          DJI Tello            │
│       (192.168.10.1)          │
└───────────────────────────────┘
```

---

## API Reference

### REST Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health`, `/api/health` | Server health status |
| `GET` | `/api/status` | Tello connection and state |
| `POST` | `/api/connect` | Initiate UDP socket connection `{local_ip}` |
| `POST` | `/api/disconnect` | Safe disconnect and cleanup |
| `GET` | `/api/network/interfaces` | Enumerate available network adapters |
| `POST` | `/api/takeoff` | Transmit takeoff command |
| `POST` | `/api/land` | Transmit land command |
| `POST` | `/api/emergency` | Immediate motor cut-off |
| `POST` | `/api/rc` | Set RC stick values `{lr, fb, ud, yaw}` |
| `POST` | `/api/move` | Directional movement command `{direction, distance}` |
| `POST` | `/api/rotate` | Directional rotation command `{direction, degrees}` |
| `POST` | `/api/video/start` | Request video stream start |
| `POST` | `/api/video/stop` | Request video stream stop |
| `POST` | `/api/video/quality` | Set video FPS and bitrate `{fps, bitrate}` |
| `POST` | `/api/video/reset_buffer` | Flush video buffer (latency reset) |
| `POST` | `/api/video/latency` | Set latency optimization mode `{mode: "normal"\|"low_latency"\|"ultra_low"}` |
| `GET` | `/video_stream` | Standard camera video stream (MJPEG) |
| `GET` | `/linetrace_stream` | Video stream with LSD overlay (MJPEG) |
| `GET` | `/api/screenshot` | Download latest video frame as PNG |
| `GET` | `/api/logs` | Enumerate available flight session CSV logs |
| `GET` | `/api/logs/latest` | Download latest flight session CSV log |
| `GET` | `/api/logs/{filename}` | Download specified flight session CSV log |
| `POST` | `/api/linetrace/start` | Start LineTrace autonomous control |
| `POST` | `/api/linetrace/stop` | Stop LineTrace autonomous control |
| `POST` | `/api/linetrace/params` | Update LineTrace filter and control parameters |
| `POST` | `/api/linetrace/preset/{name}` | Apply color preset (red, blue, yellow, black) |
| `GET` | `/api/linetrace/presets` | Get available color presets |
| `GET` | `/api/linetrace/status` | Retrieve LineTrace status and metrics |
| `POST` | `/api/linetrace/course` | Set course type `{course_type: "square"\|"other"}` |
| `POST` | `/api/linetrace/reset_laps` | Reset square course lap counter and lap timer |
| `GET` | `/api/experimental/status` | Get experimental features toggle status |
| `POST` | `/api/experimental/enable` | Enable experimental features |
| `POST` | `/api/experimental/disable` | Disable experimental features |
| `POST` | `/api/experimental/toggle` | Toggle experimental features |
| `POST` | `/api/qr/params` | Configure QR scanner `{user_name, student_id}` |
| `GET` | `/api/qr/export` | Export scanned QR records as CSV |

### WebSocket Channels

| URI | Purpose |
|---|---|
| `ws://<host>:8000/ws/control` | Bidirectional control (keyboard inputs, single commands, QR requests, video latency reset) |
| `ws://<host>:8000/ws/telemetry` | Telemetry broadcast (1 Hz status update, battery, altitude, temperature, LSD status) |

---

## Troubleshooting

1. **Connection button does not turn green**:
   - Ensure PC Wi-Fi is connected to `TELLO-XXXXXX`.
   - On dual-network PCs (Ethernet + Wi-Fi), select the `★Tello` adapter IP in Network Settings.
   - Check firewall rules for inbound/outbound UDP on ports 8889, 8890, and 11111.
2. **Video stream does not appear**:
   - When the Tello battery drops below ~10%, video transmission may shut down automatically to conserve power. Replace or recharge the battery.
3. **LineTrace does not track properly**:
   - Check contrast between floor and track. Adjust HSV sliders if lighting conditions vary.
   - High floor glare, deep shadows, or low ambient light can degrade LSD line detection.

---

## Project Structure

```
Tello-Drone-Web-Controller/
├── pyproject.toml              # Dependencies and project metadata
├── start.bat                   # Windows startup script
├── start.sh                    # macOS / Linux startup script
├── docs/
│   ├── README.md               # Japanese documentation
│   └── README_EN.md            # English documentation (this file)
├── logs/                       # Flight session CSV storage
├── tests/                      # Automated pytest suite
│   ├── test_api.py
│   ├── test_linetrace.py
│   ├── test_logger.py
│   └── test_safety.py
└── src/
    ├── __main__.py              # Entry point
    ├── tello/
    │   ├── udp_controller.py   # Raw UDP socket communication
    │   ├── state_receiver.py   # Telemetry receiver thread
    │   ├── video_receiver.py   # Video frame capture thread
    │   └── logger.py           # Flight session CSV logger
    ├── linetrace/
    │   ├── algorithm.py        # LSD line segment detector & steering logic
    │   └── engine.py           # Background tracking processor
    ├── qr/
    │   └── reader.py           # QR code reader
    └── server/
        ├── app.py              # FastAPI server
        ├── ws_handler.py       # WebSocket handler
        ├── templates/
        │   └── index.html      # Web dashboard UI
        └── static/
            ├── css/main.css    # Late-2010s dark theme stylesheet
            └── js/             # Frontend controller scripts
```

---

## Safety Notice & Disclaimer

- Autonomous tracking and web-based control provided by this software are designed for experimental and educational purposes.
- Environmental factors (drafts, lighting, reflections, Wi-Fi congestion) may cause unexpected drone behavior.
- Always fly indoors in an open, obstacle-free space away from bystanders. Ensure propeller guards are securely attached.
- Maintain visual line-of-sight at all times. Be prepared to press `Space` (Emergency Stop) or trigger manual landing if unexpected behavior occurs.

---

## License

This project is licensed under the MIT License.
