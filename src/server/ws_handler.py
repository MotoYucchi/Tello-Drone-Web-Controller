"""
WebSocket Handler — リアルタイム制御＆テレメトリ

WebSocket経由でキーボード入力、RC制御、テレメトリ配信を行う。
LineTraceの結果もリアルタイムで配信。
"""

import asyncio
import json
import time
import logging
from typing import Dict, Any, Set, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

websocket_router = APIRouter()

# 共有されるアプリケーション状態
_app_state: Dict[str, Any] = {}


def set_app_state(state: Dict[str, Any]) -> None:
    """app_stateを設定"""
    global _app_state
    _app_state = state


class ConnectionManager:
    """WebSocket接続管理"""

    def __init__(self):
        self.connections: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.add(ws)
        logger.info(f"WS接続: {len(self.connections)} 接続中")

    def disconnect(self, ws: WebSocket):
        self.connections.discard(ws)
        logger.info(f"WS切断: {len(self.connections)} 接続中")

    async def send(self, ws: WebSocket, data: dict):
        try:
            await ws.send_text(json.dumps(data, default=str))
        except Exception:
            self.disconnect(ws)

    async def broadcast(self, data: dict):
        dead = set()
        for ws in self.connections:
            try:
                await ws.send_text(json.dumps(data, default=str))
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


# =========================================================================
# メイン制御WebSocket
# =========================================================================

@websocket_router.websocket("/control")
async def ws_control(ws: WebSocket):
    """制御用WebSocket"""
    await manager.connect(ws)

    try:
        # 初期状態送信
        tello = _app_state.get('tello')
        if tello:
            await manager.send(ws, {
                'type': 'status',
                'data': tello.get_status(),
            })

        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            resp = await _handle_message(msg)
            if resp:
                await manager.send(ws, resp)

    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception as e:
        logger.error(f"WS制御エラー: {e}")
        manager.disconnect(ws)


# =========================================================================
# テレメトリ配信WebSocket
# =========================================================================

@websocket_router.websocket("/telemetry")
async def ws_telemetry(ws: WebSocket):
    """テレメトリ配信WebSocket (1秒間隔)"""
    await manager.connect(ws)

    try:
        while True:
            tello = _app_state.get('tello')
            state_recv = _app_state.get('state_receiver')
            video = _app_state.get('video')
            lt = _app_state.get('linetrace')

            data = {
                'type': 'telemetry',
                'timestamp': time.time(),
                'tello': tello.get_status() if tello else {},
                'telemetry': state_recv.get_formatted_state() if state_recv and state_recv.state else {},
                'video': video.get_stats() if video else {},
                'linetrace': lt.get_params() if lt else {},
                'linetrace_result': lt.get_last_result_info() if lt else {},
            }
            await manager.send(ws, data)
            await asyncio.sleep(1.0)

    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception as e:
        logger.error(f"WSテレメトリエラー: {e}")
        manager.disconnect(ws)


# =========================================================================
# メッセージハンドラー
# =========================================================================

async def _handle_message(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """制御メッセージを処理"""
    try:
        msg_type = msg.get('type')

        if msg_type == 'connect':
            tello = _app_state['tello']
            local_ip = msg.get('local_ip', '')
            if local_ip:
                tello.local_ip = local_ip
            success = tello.connect()
            if success:
                state_recv = _app_state['state_receiver']
                state_recv.local_ip = tello.local_ip
                state_recv.start()
            return {
                'type': 'connect_response',
                'success': success,
                'status': tello.get_status(),
            }

        elif msg_type == 'disconnect':
            tello = _app_state['tello']
            _app_state['linetrace'].active = False
            video = _app_state['video']
            if video.streaming:
                tello.stream_off()
                video.stop()
            _app_state['state_receiver'].stop()
            success = tello.disconnect()
            return {'type': 'disconnect_response', 'success': success}

        elif msg_type == 'keyboard':
            return await _handle_keyboard(msg)

        elif msg_type == 'rc_control':
            tello = _app_state['tello']
            lr = msg.get('lr', 0)
            fb = msg.get('fb', 0)
            ud = msg.get('ud', 0)
            yaw = msg.get('yaw', 0)
            tello.set_rc(lr, fb, ud, yaw)
            if any([lr, fb, ud, yaw]):
                if not tello.rc_active:
                    tello.start_rc()
            else:
                if tello.rc_active:
                    tello.stop_rc()
            return {'type': 'rc_response', 'success': True}

        elif msg_type == 'takeoff':
            tello = _app_state['tello']
            success = tello.takeoff()
            return {'type': 'takeoff_response', 'success': success}

        elif msg_type == 'land':
            tello = _app_state['tello']
            _app_state['linetrace'].active = False
            success = tello.land()
            return {'type': 'land_response', 'success': success}

        elif msg_type == 'emergency':
            tello = _app_state['tello']
            _app_state['linetrace'].active = False
            success = tello.emergency()
            return {'type': 'emergency_response', 'success': success}

        elif msg_type == 'video_start':
            tello = _app_state['tello']
            video = _app_state['video']
            if tello.is_connected:
                tello.stream_on()
                import time as t
                t.sleep(2)
                success = video.start()
            else:
                success = False
            return {'type': 'video_response', 'success': success}

        elif msg_type == 'video_stop':
            tello = _app_state['tello']
            video = _app_state['video']
            video.stop()
            if tello.is_connected:
                tello.stream_off()
            return {'type': 'video_response', 'success': True}

        elif msg_type == 'linetrace_start':
            lt = _app_state['linetrace']
            tello = _app_state['tello']
            if tello.is_flying:
                lt.active = True
                if not tello.rc_active:
                    tello.start_rc()
                return {'type': 'linetrace_response', 'success': True}
            return {'type': 'linetrace_response', 'success': False}

        elif msg_type == 'linetrace_stop':
            lt = _app_state['linetrace']
            tello = _app_state['tello']
            lt.active = False
            tello.set_rc(0, 0, 0, 0)
            return {'type': 'linetrace_response', 'success': True}

        elif msg_type == 'linetrace_preset':
            lt = _app_state['linetrace']
            preset = msg.get('preset', '')
            success = lt.apply_preset(preset)
            return {'type': 'linetrace_params', 'success': success, 'params': lt.get_params()}

        elif msg_type == 'linetrace_params':
            lt = _app_state['linetrace']
            lt.set_params(msg.get('params', {}))
            return {'type': 'linetrace_params', 'success': True, 'params': lt.get_params()}

        elif msg_type == 'qr_scan':
            qr = _app_state['qr']
            video = _app_state['video']
            frame = video.get_frame()
            if frame is None:
                return {'type': 'qr_response', 'success': False, 'message': 'フレームなし'}
            result = qr.process_detection(frame)
            result['type'] = 'qr_response'
            return result

        else:
            return {'type': 'error', 'message': f'不明なメッセージタイプ: {msg_type}'}

    except Exception as e:
        logger.error(f"メッセージ処理エラー: {e}")
        return {'type': 'error', 'message': str(e)}


async def _handle_keyboard(msg: Dict[str, Any]) -> Dict[str, Any]:
    """キーボード操作処理"""
    tello = _app_state['tello']
    action = msg.get('action')  # press, release, single
    key = msg.get('key', '')

    # 単発キー
    if action == 'single':
        if key == 't':
            success = tello.takeoff()
            return {'type': 'keyboard_response', 'success': success, 'action': 'takeoff'}
        elif key == 'l':
            _app_state['linetrace'].active = False
            success = tello.land()
            return {'type': 'keyboard_response', 'success': success, 'action': 'land'}
        elif key == 'space':
            _app_state['linetrace'].active = False
            success = tello.emergency()
            return {'type': 'keyboard_response', 'success': success, 'action': 'emergency'}

    # RC制御キー（press/release で連続制御）
    # キー状態管理
    if not hasattr(_handle_keyboard, '_keys'):
        _handle_keyboard._keys = {}

    if action == 'press':
        _handle_keyboard._keys[key] = True
    elif action == 'release':
        _handle_keyboard._keys[key] = False

    keys = _handle_keyboard._keys
    speed = 50
    rot_speed = 60

    lr = 0
    fb = 0
    ud = 0
    yaw = 0

    if keys.get('w'):
        fb = speed
    if keys.get('s'):
        fb = -speed
    if keys.get('a'):
        lr = -speed
    if keys.get('d'):
        lr = speed
    if keys.get('r'):
        ud = speed
    if keys.get('f'):
        ud = -speed
    if keys.get('q'):
        yaw = -rot_speed
    if keys.get('e'):
        yaw = rot_speed

    tello.set_rc(lr, fb, ud, yaw)

    if any([lr, fb, ud, yaw]):
        if not tello.rc_active:
            tello.start_rc()
    else:
        if tello.rc_active:
            tello.stop_rc()

    return {
        'type': 'keyboard_response',
        'success': True,
        'rc': {'lr': lr, 'fb': fb, 'ud': ud, 'yaw': yaw},
    }
