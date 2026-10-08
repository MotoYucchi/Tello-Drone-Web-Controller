"""
FastAPI メインアプリケーション

Tello Drone Web Controller のメインサーバー。
WebSocket + REST API + 映像ストリーミング + 飛行ログ + 静止画撮影を統合。
"""

import asyncio
import logging
import os
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Dict, Any

import cv2
import numpy as np
from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from ..tello.udp_controller import TelloUDPController
from ..tello.state_receiver import TelloStateReceiver
from ..tello.video_receiver import TelloVideoReceiver
from ..tello.logger import FlightLogger
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
    app_state['logger'] = FlightLogger()

    app_state['loop'] = asyncio.get_running_loop()
    app_state['qr_last_scan'] = 0.0

    # テレメトリ更新コールバック
    def on_telemetry_update(state: Dict[str, Any]):
        fl: FlightLogger = app_state.get('logger')
        if fl:
            fl.update_telemetry(state)

    app_state['state_receiver'].on_state_update = on_telemetry_update

    def send_to_pashatoku(qr_text: str):
        """PashatokuへQRデータを送信"""
        import urllib.request
        url = "http://192.168.10.39:8080/api/qr/receive"
        
        user_name = app_state.get('pashatoku_user_name', '')
        student_id = app_state.get('pashatoku_student_id', '')
        
        headers = {
            "X-User-Name": user_name,
            "X-Student-Id": student_id,
            "Content-Type": "text/plain; charset=utf-8"
        }
        data = qr_text.encode('utf-8')
        req = urllib.request.Request(url, data=data, headers=headers, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=3.0) as f:
                logger.info(f"Pashatokuへ送信成功: {f.status} {qr_text}")
        except Exception as e:
            logger.error(f"Pashatokuへの送信に失敗しました: {e}")

    def process_video_frame(frame: np.ndarray):
        lt: LineTraceEngine = app_state.get('linetrace')
        tello: TelloUDPController = app_state.get('tello')
        fl: FlightLogger = app_state.get('logger')
        
        # QRコードの自動スキャン（1秒に1回）
        import time
        now = time.time()
        if now - app_state.get('qr_last_scan', 0.0) > 1.0:
            app_state['qr_last_scan'] = now
            qr: QRCodeReader = app_state.get('qr')
            if qr:
                qr_res = qr.process_detection(frame)
                if qr_res.get('success') and qr_res.get('newly_stored'):
                    if fl:
                        fl.log_event(f"QR Scanned: {qr_res.get('qr_text')}")
                    # Pashatokuに送信
                    loop = app_state.get('loop')
                    if loop:
                        loop.run_in_executor(None, send_to_pashatoku, qr_res.get('qr_text'))

                    qr_res['type'] = 'qr_response'
                    if loop:
                        from .ws_handler import manager
                        asyncio.run_coroutine_threadsafe(manager.broadcast(qr_res), loop)

        if lt and tello:
            # ライントレース処理
            result = lt.process_frame(frame)
            if fl:
                fl.update_linetrace(lt.get_last_result_info())

            if lt.active:
                # LineTraceEngine が決定したRC制御値 (追従・ダンピング・自動復帰サーチ) を適用
                rc = lt.get_rc_values(result)
                tello.set_rc(rc['lr'], rc['fb'], 0, rc['yaw'])
                if fl:
                    mode = "linetrace" if result.detected else f"lt_{result.tracking_state}"
                    fl.update_rc(rc['lr'], rc['fb'], 0, rc['yaw'], mode=mode)
    
    app_state['video'].on_frame = process_video_frame

    # WebSocket ハンドラーに状態を共有
    set_app_state(app_state)

    logger.info("=== Tello Web Controller 起動完了 ===")
    yield

    # クリーンアップ
    logger.info("=== Tello Web Controller 終了中 ===")
    try:
        fl: FlightLogger = app_state.get('logger')
        if fl:
            fl.stop_session()

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
    version="2.1.0",
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
    camera_mode: str = Field(default="standard", description="standard (通常機体) または downward (改造機体)")
    h_min: int = Field(default=0, ge=0, le=179)
    h_max: int = Field(default=179, ge=0, le=179)
    s_min: int = Field(default=0, ge=0, le=255)
    s_max: int = Field(default=255, ge=0, le=255)
    v_min: int = Field(default=0, ge=0, le=255)
    v_max: int = Field(default=255, ge=0, le=255)
    gaussian_ksize: int = Field(default=5, ge=1, le=31)
    forward_speed: int = Field(default=15, ge=0, le=100)
    deadzone: float = Field(default=20.0, ge=0, le=200)
    yaw_limit: float = Field(default=60.0, ge=0, le=100)


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
    fl: FlightLogger = app_state['logger']

    if tello.is_connected:
        return {"success": True, "message": "既に接続済み", "status": tello.get_status()}

    if req.local_ip:
        tello.local_ip = req.local_ip

    success = await asyncio.to_thread(tello.connect)
    if success:
        # テレメトリ受信開始
        state_recv: TelloStateReceiver = app_state['state_receiver']
        state_recv.local_ip = tello.local_ip
        state_recv.start()

        # フライトログセッション開始
        if fl:
            fl.start_session()
            fl.log_event("Connected to Tello")

    return {
        "success": success,
        "message": "接続成功" if success else "接続失敗",
        "status": tello.get_status(),
    }


@app.post("/api/disconnect")
async def disconnect_tello():
    """Telloから切断 (バッテリー切れ時もフリーズせず即座にクリーンアップ)"""
    tello: TelloUDPController = app_state['tello']
    fl: FlightLogger = app_state['logger']

    # フライトログ記録終了
    if fl:
        fl.log_event("Disconnected from Tello")
        fl.stop_session()

    # LineTrace停止
    app_state['linetrace'].active = False

    # 映像停止
    video: TelloVideoReceiver = app_state['video']
    if video.streaming:
        await asyncio.to_thread(tello.stream_off, False)
        video.stop()

    # テレメトリ停止
    app_state['state_receiver'].stop()

    success = await asyncio.to_thread(tello.disconnect, True)
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
    fl: FlightLogger = app_state['logger']
    if not tello.is_connected:
        raise HTTPException(400, "未接続")
    if fl:
        fl.log_event("Takeoff requested")
    success = await asyncio.to_thread(tello.takeoff)
    if fl and success:
        fl.log_event("Takeoff success")
    return {"success": success}


@app.post("/api/land")
async def land():
    tello: TelloUDPController = app_state['tello']
    fl: FlightLogger = app_state['logger']
    if not tello.is_connected:
        raise HTTPException(400, "未接続")
    app_state['linetrace'].active = False
    if fl:
        fl.log_event("Land requested")
    success = await asyncio.to_thread(tello.land)
    if fl and success:
        fl.log_event("Land success")
    return {"success": success}


@app.post("/api/emergency")
async def emergency():
    tello: TelloUDPController = app_state['tello']
    fl: FlightLogger = app_state['logger']
    if not tello.is_connected:
        raise HTTPException(400, "未接続")
    app_state['linetrace'].active = False
    if fl:
        fl.log_event("EMERGENCY STOP")
    success = await asyncio.to_thread(tello.emergency)
    return {"success": success}


@app.post("/api/move")
async def move(req: MoveRequest):
    tello: TelloUDPController = app_state['tello']
    fl: FlightLogger = app_state['logger']
    if not tello.is_flying:
        raise HTTPException(400, "飛行中ではありません")
    if fl:
        fl.log_event(f"Move: {req.direction} {req.distance}cm")
    success = tello.move(req.direction, req.distance)
    return {"success": success}


@app.post("/api/rotate")
async def rotate(req: RotateRequest):
    tello: TelloUDPController = app_state['tello']
    fl: FlightLogger = app_state['logger']
    if not tello.is_flying:
        raise HTTPException(400, "飛行中ではありません")
    if fl:
        fl.log_event(f"Rotate: {req.direction} {req.angle}deg")
    success = tello.rotate(req.direction, req.angle)
    return {"success": success}


@app.post("/api/rc")
async def rc_control(req: RCRequest):
    tello: TelloUDPController = app_state['tello']
    fl: FlightLogger = app_state['logger']
    if not tello.is_connected:
        raise HTTPException(400, "未接続")
    tello.set_rc(req.lr, req.fb, req.ud, req.yaw)
    if fl:
        fl.update_rc(req.lr, req.fb, req.ud, req.yaw, mode="manual")
    if any([req.lr, req.fb, req.ud, req.yaw]):
        if not tello.rc_active:
            tello.start_rc()
    else:
        if tello.rc_active:
            tello.stop_rc()
    return {"success": True}


# =========================================================================
# 映像 API & 静止画撮影
# =========================================================================

@app.post("/api/video/start")
async def start_video():
    tello: TelloUDPController = app_state['tello']
    video: TelloVideoReceiver = app_state['video']
    if not tello.is_connected:
        raise HTTPException(400, "未接続")
    if video.streaming:
        return {"success": True, "message": "既にストリーミング中"}

    await asyncio.to_thread(tello.stream_on)
    await asyncio.sleep(2.0)
    success = await asyncio.to_thread(video.start)
    return {"success": success}


@app.post("/api/video/stop")
async def stop_video():
    tello: TelloUDPController = app_state['tello']
    video: TelloVideoReceiver = app_state['video']
    await asyncio.to_thread(video.stop)
    if tello.is_connected:
        await asyncio.to_thread(tello.stream_off)
    return {"success": True}


@app.post("/api/video/quality")
async def set_video_quality(req: VideoQualityRequest):
    video: TelloVideoReceiver = app_state['video']
    video.set_quality(req.width, req.height, req.quality)
    return {"success": True}


@app.get("/api/screenshot")
async def get_screenshot():
    """最新フレームから静止画(PNG)を生成しダウンロード"""
    video: TelloVideoReceiver = app_state.get('video')
    if not video or not video.streaming:
        raise HTTPException(400, "映像ストリーミングが開始されていません")
    frame = video.get_frame()
    if frame is None or frame.size == 0:
        raise HTTPException(400, "フレームを取得できませんでした")

    ok, png_data = cv2.imencode('.png', frame)
    if not ok:
        raise HTTPException(500, "PNGエンコードに失敗しました")

    now_str = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    filename = f"TELLO_{now_str}.png"

    fl: FlightLogger = app_state.get('logger')
    if fl:
        fl.log_event(f"Screenshot taken: {filename}")

    return Response(
        content=png_data.tobytes(),
        media_type="image/png",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )


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


def generate_linetrace_mjpeg():
    import time
    video: TelloVideoReceiver = app_state['video']
    lt: LineTraceEngine = app_state['linetrace']
    
    blank_frame = np.zeros((180, 480, 3), dtype=np.uint8)
    
    while video.streaming:
        try:
            result = lt._last_result
            if result and result.debug_frame is not None:
                img = result.debug_frame
            else:
                img = blank_frame

            ok, encoded = cv2.imencode('.jpg', img, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            if ok:
                yield (
                    b'--frame\r\n'
                    b'Content-Type: image/jpeg\r\n\r\n' + encoded.tobytes() + b'\r\n'
                )
                time.sleep(0.05)
                continue
        except GeneratorExit:
            break
        except Exception as e:
            logger.debug(f"linetrace_mjpeg encode error: {e}")
        time.sleep(0.05)


@app.get("/linetrace_stream")
async def linetrace_stream():
    """ライントレース デバッグ用MJPEG映像ストリーム"""
    video: TelloVideoReceiver = app_state['video']
    if not video.streaming:
        raise HTTPException(503, "映像ストリーミング未開始")
    return StreamingResponse(
        generate_linetrace_mjpeg(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


# =========================================================================
# LineTrace API
# =========================================================================

@app.post("/api/linetrace/start")
async def start_linetrace():
    lt: LineTraceEngine = app_state['linetrace']
    tello: TelloUDPController = app_state['tello']
    fl: FlightLogger = app_state['logger']

    if not tello.is_flying:
        raise HTTPException(400, "飛行中ではありません")
    lt.active = True

    if fl:
        fl.log_event("LineTrace started")

    # RC制御開始
    if not tello.rc_active:
        tello.start_rc()

    return {"success": True, "message": "LineTrace開始"}


@app.post("/api/linetrace/stop")
async def stop_linetrace():
    lt: LineTraceEngine = app_state['linetrace']
    tello: TelloUDPController = app_state['tello']
    fl: FlightLogger = app_state['logger']

    lt.active = False
    tello.set_rc(0, 0, 0, 0)
    if fl:
        fl.log_event("LineTrace stopped")
        fl.update_rc(0, 0, 0, 0, mode="manual")

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
# フライトログ (Timeline CSV) API
# =========================================================================

@app.get("/api/logs")
async def list_logs():
    """保存されたフライトログ一覧を返す"""
    fl: FlightLogger = app_state.get('logger')
    if not fl:
        return {"logs": []}
    return {"logs": fl.list_logs()}


@app.get("/api/logs/latest")
async def download_latest_log():
    """最新セッションのフライトログCSVをダウンロード"""
    fl: FlightLogger = app_state.get('logger')
    if not fl:
        raise HTTPException(404, "ロガーが利用できません")
    path = fl.get_latest_log_path()
    if not path or not os.path.exists(path):
        raise HTTPException(404, "ログファイルが見つかりません")
    filename = os.path.basename(path)
    return FileResponse(path=path, media_type="text/csv", filename=filename)


@app.get("/api/logs/{filename}")
async def download_log(filename: str):
    """指定されたフライトログCSVをダウンロード (パストラバーサル防止)"""
    safe_filename = os.path.basename(filename)
    import re
    # 厳格なファイル名パターンチェック (TELLO_YYYY-MM-DD-HH-mm-ss(_N)?.csv のみ許可)
    if not re.match(r"^TELLO_\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}(_\d+)?\.csv$", safe_filename):
        raise HTTPException(400, "無効なログファイル名フォーマットです")

    fl: FlightLogger = app_state.get('logger')
    if not fl:
        raise HTTPException(404, "ロガーが利用できません")
    filepath = os.path.join(fl.log_dir, safe_filename)
    if not os.path.exists(filepath):
        raise HTTPException(404, f"指定のログファイルが存在しません: {safe_filename}")
    return FileResponse(path=filepath, media_type="text/csv", filename=safe_filename)


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


@app.delete("/api/qr/links/{qr_text:path}")
async def delete_qr_link(qr_text: str):
    qr: QRCodeReader = app_state['qr']
    success = qr.delete_link(qr_text)
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
