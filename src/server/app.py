"""
FastAPI メインアプリケーション

Tello Drone Web Controller のメインサーバー。
WebSocket + REST API + 映像ストリーミングを統合。
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from ..tello.udp_controller import TelloUDPController
from ..tello.state_receiver import TelloStateReceiver
from ..tello.video_receiver import TelloVideoReceiver
from ..linetrace.engine import LineTraceEngine, COLOR_PRESETS
from ..qr.reader import QRCodeReader
from .ws_handler import websocket_router, set_app_state

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# グローバル状態
app_state: Dict[str, Any] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """アプリケーションライフサイクル"""
    logger.info("=== Tello Web Controller 起動中 ===")

    # コンポーネント初期化
    app_state['tello'] = TelloUDPController()
    app_state['state_receiver'] = TelloStateReceiver()
    app_state['video'] = TelloVideoReceiver()
    app_state['linetrace'] = LineTraceEngine()
    app_state['qr'] = QRCodeReader()

    # WebSocket ハンドラーに状態を共有
    set_app_state(app_state)

    logger.info("=== Tello Web Controller 起動完了 ===")
    yield

    # クリーンアップ
    logger.info("=== Tello Web Controller 終了中 ===")
    try:
        tello: TelloUDPController = app_state.get('tello')
        if tello and tello.is_connected:
            tello.disconnect()

        video: TelloVideoReceiver = app_state.get('video')
        if video and video.streaming:
            video.stop()

        state_recv: TelloStateReceiver = app_state.get('state_receiver')
        if state_recv:
            state_recv.stop()
    except Exception as e:
        logger.error(f"クリーンアップエラー: {e}")

    logger.info("=== Tello Web Controller 終了完了 ===")


# FastAPI アプリケーション
app = FastAPI(
    title="Tello Drone Web Controller",
    description="Telloドローン Web制御アプリケーション",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# パス設定
_current_dir = os.path.dirname(os.path.abspath(__file__))
_static_dir = os.path.join(_current_dir, "static")
_templates_dir = os.path.join(_current_dir, "templates")

if os.path.exists(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

templates = Jinja2Templates(directory=_templates_dir)

# WebSocket ルーター登録
app.include_router(websocket_router, prefix="/ws")


# =========================================================================
# リクエストモデル
# =========================================================================

class ConnectRequest(BaseModel):
    local_ip: str = Field(default='', description="バインドするローカルIP（空=自動検出）")

class MoveRequest(BaseModel):
    direction: str = Field(..., description="forward/back/left/right/up/down")
    distance: int = Field(default=30, ge=20, le=500)

class RotateRequest(BaseModel):
    direction: str = Field(..., description="cw/ccw")
    angle: int = Field(default=90, ge=1, le=360)

class RCRequest(BaseModel):
    lr: int = Field(default=0, ge=-100, le=100)
    fb: int = Field(default=0, ge=-100, le=100)
    ud: int = Field(default=0, ge=-100, le=100)
    yaw: int = Field(default=0, ge=-100, le=100)

class VideoQualityRequest(BaseModel):
    width: int = Field(default=640, ge=160, le=1920)
    height: int = Field(default=480, ge=120, le=1080)
    quality: int = Field(default=80, ge=10, le=100)

class LineTraceParamsRequest(BaseModel):
    h_min: int = Field(default=0, ge=0, le=179)
    h_max: int = Field(default=179, ge=0, le=179)
    s_min: int = Field(default=0, ge=0, le=255)
    s_max: int = Field(default=255, ge=0, le=255)
    v_min: int = Field(default=0, ge=0, le=255)
    v_max: int = Field(default=255, ge=0, le=255)
    forward_speed: int = Field(default=10, ge=0, le=100)
    deadzone: float = Field(default=50.0, ge=0, le=200)
    yaw_limit: float = Field(default=70.0, ge=0, le=100)


# =========================================================================
# ページルート
# =========================================================================

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """メインページ"""
    return templates.TemplateResponse(name="index.html", request=request)


# =========================================================================
# 接続管理 API
# =========================================================================

@app.post("/api/connect")
async def connect_tello(req: ConnectRequest):
    """Telloに接続"""
    tello: TelloUDPController = app_state['tello']
    if tello.is_connected:
        return {"success": True, "message": "既に接続済み", "status": tello.get_status()}

    if req.local_ip:
        tello.local_ip = req.local_ip

    success = tello.connect()
    if success:
        # テレメトリ受信も開始
        state_recv: TelloStateReceiver = app_state['state_receiver']
        state_recv.local_ip = tello.local_ip
        state_recv.start()

    return {
        "success": success,
        "message": "接続成功" if success else "接続失敗",
        "status": tello.get_status(),
    }


@app.post("/api/disconnect")
async def disconnect_tello():
    """Telloから切断"""
    tello: TelloUDPController = app_state['tello']

    # LineTrace停止
    app_state['linetrace'].active = False

    # 映像停止
    video: TelloVideoReceiver = app_state['video']
    if video.streaming:
        tello.stream_off()
        video.stop()

    # テレメトリ停止
    app_state['state_receiver'].stop()

    success = tello.disconnect()
    return {"success": success, "message": "切断完了" if success else "切断失敗"}


@app.get("/api/status")
async def get_status():
    """ステータス取得"""
    tello: TelloUDPController = app_state['tello']
    state_recv: TelloStateReceiver = app_state['state_receiver']
    video: TelloVideoReceiver = app_state['video']
    lt: LineTraceEngine = app_state['linetrace']

    return {
        "tello": tello.get_status(),
        "telemetry": state_recv.get_formatted_state() if state_recv.state else {},
        "video": video.get_stats(),
        "linetrace": lt.get_params(),
    }


@app.get("/api/network/interfaces")
async def get_network_interfaces():
    """ネットワークインターフェース一覧"""
    interfaces = TelloUDPController.list_network_interfaces()
    return {"interfaces": interfaces}


# =========================================================================
# 飛行制御 API
# =========================================================================

@app.post("/api/takeoff")
async def takeoff():
    tello: TelloUDPController = app_state['tello']
    if not tello.is_connected:
        raise HTTPException(400, "未接続")
    success = tello.takeoff()
    return {"success": success}


@app.post("/api/land")
async def land():
    tello: TelloUDPController = app_state['tello']
    if not tello.is_connected:
        raise HTTPException(400, "未接続")
    app_state['linetrace'].active = False
    success = tello.land()
    return {"success": success}


@app.post("/api/emergency")
async def emergency():
    tello: TelloUDPController = app_state['tello']
    if not tello.is_connected:
        raise HTTPException(400, "未接続")
    app_state['linetrace'].active = False
    success = tello.emergency()
    return {"success": success}


@app.post("/api/move")
async def move(req: MoveRequest):
    tello: TelloUDPController = app_state['tello']
    if not tello.is_flying:
        raise HTTPException(400, "飛行中ではありません")
    success = tello.move(req.direction, req.distance)
    return {"success": success}


@app.post("/api/rotate")
async def rotate(req: RotateRequest):
    tello: TelloUDPController = app_state['tello']
    if not tello.is_flying:
        raise HTTPException(400, "飛行中ではありません")
    success = tello.rotate(req.direction, req.angle)
    return {"success": success}


@app.post("/api/rc")
async def rc_control(req: RCRequest):
    tello: TelloUDPController = app_state['tello']
    if not tello.is_connected:
        raise HTTPException(400, "未接続")
    tello.set_rc(req.lr, req.fb, req.ud, req.yaw)
    if any([req.lr, req.fb, req.ud, req.yaw]):
        if not tello.rc_active:
            tello.start_rc()
    else:
        if tello.rc_active:
            tello.stop_rc()
    return {"success": True}


# =========================================================================
# 映像 API
# =========================================================================

@app.post("/api/video/start")
async def start_video():
    tello: TelloUDPController = app_state['tello']
    video: TelloVideoReceiver = app_state['video']
    if not tello.is_connected:
        raise HTTPException(400, "未接続")
    if video.streaming:
        return {"success": True, "message": "既にストリーミング中"}

    tello.stream_on()
    import time
    time.sleep(2)
    success = video.start()
    return {"success": success}


@app.post("/api/video/stop")
async def stop_video():
    tello: TelloUDPController = app_state['tello']
    video: TelloVideoReceiver = app_state['video']
    video.stop()
    if tello.is_connected:
        tello.stream_off()
    return {"success": True}


@app.post("/api/video/quality")
async def set_video_quality(req: VideoQualityRequest):
    video: TelloVideoReceiver = app_state['video']
    video.set_quality(req.width, req.height, req.quality)
    return {"success": True}


@app.get("/video_stream")
async def video_stream():
    """MJPEG映像ストリーム"""
    video: TelloVideoReceiver = app_state['video']
    if not video.streaming:
        raise HTTPException(503, "映像ストリーミング未開始")
    return StreamingResponse(
        video.generate_mjpeg_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


# =========================================================================
# LineTrace API
# =========================================================================

@app.post("/api/linetrace/start")
async def start_linetrace():
    lt: LineTraceEngine = app_state['linetrace']
    tello: TelloUDPController = app_state['tello']
    if not tello.is_flying:
        raise HTTPException(400, "飛行中ではありません")
    lt.active = True

    # RC制御開始
    if not tello.rc_active:
        tello.start_rc()

    return {"success": True, "message": "LineTrace開始"}


@app.post("/api/linetrace/stop")
async def stop_linetrace():
    lt: LineTraceEngine = app_state['linetrace']
    tello: TelloUDPController = app_state['tello']
    lt.active = False
    tello.set_rc(0, 0, 0, 0)
    return {"success": True, "message": "LineTrace停止"}


@app.post("/api/linetrace/params")
async def set_linetrace_params(req: LineTraceParamsRequest):
    lt: LineTraceEngine = app_state['linetrace']
    lt.set_params(req.model_dump())
    return {"success": True, "params": lt.get_params()}


@app.post("/api/linetrace/preset/{preset_name}")
async def apply_linetrace_preset(preset_name: str):
    lt: LineTraceEngine = app_state['linetrace']
    if lt.apply_preset(preset_name):
        return {"success": True, "params": lt.get_params()}
    raise HTTPException(400, f"不明なプリセット: {preset_name}")


@app.get("/api/linetrace/presets")
async def get_linetrace_presets():
    return {"presets": COLOR_PRESETS}


@app.get("/api/linetrace/status")
async def get_linetrace_status():
    lt: LineTraceEngine = app_state['linetrace']
    return {
        "params": lt.get_params(),
        "result": lt.get_last_result_info(),
    }


# =========================================================================
# QRコード API
# =========================================================================

@app.post("/api/qr/scan")
async def scan_qr():
    qr: QRCodeReader = app_state['qr']
    video: TelloVideoReceiver = app_state['video']
    if not video.streaming:
        raise HTTPException(400, "映像ストリーミング未開始")
    frame = video.get_frame()
    if frame is None:
        raise HTTPException(400, "フレーム取得失敗")
    return qr.process_detection(frame)


@app.get("/api/qr/links")
async def get_qr_links():
    qr: QRCodeReader = app_state['qr']
    links = qr.get_stored_links()
    return {"success": True, "links": links, "count": len(links)}


@app.delete("/api/qr/links/{three_digit}")
async def delete_qr_link(three_digit: str):
    qr: QRCodeReader = app_state['qr']
    success = qr.delete_link(three_digit)
    return {"success": success}


@app.delete("/api/qr/links")
async def clear_qr_links():
    qr: QRCodeReader = app_state['qr']
    success = qr.clear_links()
    return {"success": success}


# =========================================================================
# ヘルスチェック
# =========================================================================

@app.get("/health")
async def health():
    tello: TelloUDPController = app_state.get('tello')
    return {
        "status": "healthy",
        "tello_connected": tello.is_connected if tello else False,
    }
