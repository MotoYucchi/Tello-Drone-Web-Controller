# Tello Drone Web Controller

A web-based DJI Tello drone controller with WiFi interface binding, LineTrace, and a responsive dark-mode UI.

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Requirements](#requirements)
- [Setup](#setup)
- [Usage](#usage)
  - [Connecting to Tello](#connecting-to-tello)
  - [Flight Controls](#flight-controls)
  - [Keyboard Controls](#keyboard-controls)
  - [LineTrace](#linetrace)
  - [QR Code Scanner](#qr-code-scanner)
  - [Video Streaming](#video-streaming)
- [Network Architecture](#network-architecture)
- [API Reference](#api-reference)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Overview

This application lets you control a DJI Tello drone from your browser. It uses raw UDP sockets bound to the WiFi network interface, ensuring reliable communication even when your PC has multiple network connections (e.g., Ethernet + WiFi).

### Key Features

- **Network Interface Binding**: Raw UDP sockets bound directly to the WiFi interface
- **LineTrace**: Automatic line-following using HSV color filtering
- **QR Code Scanner**: Enhanced QR detection with multiple preprocessing fallbacks
- **Responsive UI**: Dark-mode glassmorphism UI that works on desktop, tablet, and mobile
- **Real-time Control**: WebSocket-based keyboard and RC control

---

## Features

| Feature | Description |
|---------|-------------|
| Connect/Disconnect | Auto-detect WiFi interface + manual selection |
| Takeoff/Land/Emergency | Button or keyboard (T/L/Space) |
| Movement Control | WASD (horizontal), R/F (vertical), Q/E (rotation) |
| Video Streaming | Real-time MJPEG video feed |
| LineTrace | HSV color-space line tracking with auto-follow |
| QR Code Scanner | Detect QR codes from video and store links |
| Telemetry | Real-time battery, altitude, temperature, flight time |
| Network Settings | Interface selection, video quality |

---

## Requirements

| Item | Requirement |
|------|-------------|
| OS | Windows 10/11, macOS, Linux |
| Python | 3.11+ |
| Package Manager | [uv](https://docs.astral.sh/uv/) |
| Drone | DJI Tello / Tello EDU |
| Browser | Chrome, Edge, Firefox (latest) |

---

## Setup

### Quick Setup (Recommended)

Use the included launcher scripts for automatic setup:

**Windows:**
```
start.bat
```

**macOS / Linux:**
```bash
chmod +x start.sh
./start.sh
```

### Manual Setup

#### 1. Install uv

**Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**macOS / Linux:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

#### 2. Install Dependencies

```bash
cd web_drone_controller
uv sync
```

#### 3. Start the Server

```bash
uv run python -m src
```

#### 4. Open in Browser

```
http://localhost:8000
```

---

## Usage

### Connecting to Tello

1. Connect your PC's WiFi to the Tello network (SSID: `TELLO-XXXXXX`)
2. Open `http://localhost:8000` in your browser
3. Click the "Connect" button in the header
4. Wait for the status to change to "Connected"

> **💡 Dual Network Tip**: If you have Ethernet + WiFi, select the Tello interface (marked with ★Tello) in the Network Settings panel before connecting.

### Flight Controls

| Button | Action |
|--------|--------|
| Takeoff | Drone ascends to ~1m height |
| Land | Lands in place |
| Emergency | Immediately stops all motors (with confirmation) |

### Keyboard Controls

| Key | Action |
|-----|--------|
| W | Move forward |
| S | Move backward |
| A | Move left |
| D | Move right |
| R | Ascend |
| F | Descend |
| Q | Rotate counter-clockwise |
| E | Rotate clockwise |
| T | Takeoff |
| L | Land |
| Space | Emergency stop |

> **⚠️ Note**: Keyboard controls are disabled when a text input has focus.

### LineTrace

1. Start video streaming
2. Select a color preset (Red/Blue/Yellow/Black) or adjust HSV sliders manually
3. Toggle LineTrace ON
4. The drone will automatically follow the detected line

#### HSV Parameters

| Parameter | Description | Range |
|-----------|-------------|-------|
| H min/max | Hue range | 0-179 |
| S min/max | Saturation range | 0-255 |
| V min/max | Value (brightness) range | 0-255 |
| Speed | Forward speed | 0-100 |

### QR Code Scanner

1. Click "Scan" while video is streaming
2. Detected 3-digit numbers generate and save links automatically
3. Click "Refresh" to update the stored links list

### Video Streaming

1. After connecting, click the "Start Video" button
2. Click the stop button (■) to stop video
3. Click the camera icon to save a screenshot

---

## Network Architecture

```
┌─────────────────┐     WiFi (192.168.10.x)      ┌──────────┐
│    PC            │◄──────────────────────────────►│  Tello   │
│                  │        UDP :8889 (cmd)         │          │
│  ┌─────────┐    │        UDP :8890 (state)       │          │
│  │ FastAPI  │    │        UDP :11111 (video)      │          │
│  │ :8000    │    │                                └──────────┘
│  └─────────┘    │
│                  │     Ethernet (different subnet)
│                  │◄──────────────── Internet
└─────────────────┘
```

**Key Point**: By binding the UDP socket to the `192.168.10.x` local IP, traffic is isolated from the Ethernet interface, ensuring packets are sent over WiFi to the Tello.

---

## API Reference

### REST API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/connect` | Connect to Tello |
| POST | `/api/disconnect` | Disconnect from Tello |
| GET | `/api/status` | Get current status |
| GET | `/api/network/interfaces` | List network interfaces |
| POST | `/api/takeoff` | Takeoff |
| POST | `/api/land` | Land |
| POST | `/api/emergency` | Emergency stop |
| POST | `/api/move` | Move `{direction, distance}` |
| POST | `/api/rotate` | Rotate `{direction, angle}` |
| POST | `/api/rc` | RC control `{lr, fb, ud, yaw}` |
| POST | `/api/video/start` | Start video |
| POST | `/api/video/stop` | Stop video |
| POST | `/api/video/quality` | Set quality `{width, height, quality}` |
| GET | `/video_stream` | MJPEG stream |
| POST | `/api/linetrace/start` | Start LineTrace |
| POST | `/api/linetrace/stop` | Stop LineTrace |
| POST | `/api/linetrace/params` | Set LineTrace parameters |
| POST | `/api/linetrace/preset/{name}` | Apply color preset |
| GET | `/api/linetrace/presets` | List presets |
| POST | `/api/qr/scan` | Scan QR code |
| GET | `/api/qr/links` | List stored links |
| DELETE | `/api/qr/links/{num}` | Delete a link |

### WebSocket Endpoints

| Path | Description |
|------|-------------|
| `ws://localhost:8000/ws/control` | Control channel (send/receive commands) |
| `ws://localhost:8000/ws/telemetry` | Telemetry broadcast (1-second interval) |

---

## Troubleshooting

### Cannot connect to Tello

1. Verify WiFi is connected to the Tello network (`TELLO-XXXXXX`)
2. Check the correct interface is selected in Network Settings
3. Ensure firewall is not blocking UDP ports 8889, 8890, 11111
4. Ensure no other application is using port 8889

### Video not displaying

1. Confirm the drone is connected
2. Click "Start Video" again
3. Check browser console for errors
4. Verify Tello battery is sufficient

### LineTrace not responding

1. Ensure video streaming is active
2. Verify HSV parameters match the target line color
3. Check lighting conditions are adequate

### Cannot communicate with Tello when Ethernet is connected

1. Explicitly select the ★Tello interface in Network Settings
2. Click "Refresh" to reload interfaces
3. If no `192.168.10.x` IP appears, verify WiFi connection

---

## License

MIT License
