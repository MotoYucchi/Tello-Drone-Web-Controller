"""
Tello State Receiver — テレメトリデータ受信

Telloはポート8890にテレメトリデータを自動送信する。
このモジュールはそのデータを受信してパースする。
"""

import socket
import threading
import logging
from typing import Optional, Callable, Dict, Any

logger = logging.getLogger(__name__)


class TelloStateReceiver:
    """Telloテレメトリ受信クラス (port 8890)"""

    STATE_PORT = 8890

    def __init__(self, local_ip: str = ''):
        self.local_ip = local_ip
        self.sock: Optional[socket.socket] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # 最新のテレメトリデータ
        self.state: Dict[str, Any] = {}

        # コールバック
        self.on_state_update: Optional[Callable[[Dict[str, Any]], None]] = None

    def start(self) -> bool:
        """受信開始"""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.settimeout(3.0)
            self.sock.bind((self.local_ip, self.STATE_PORT))

            self._running = True
            self._thread = threading.Thread(
                target=self._receive_loop, daemon=True, name='tello-state'
            )
            self._thread.start()
            logger.info(f"テレメトリ受信開始 (port {self.STATE_PORT})")
            return True
        except Exception as e:
            logger.error(f"テレメトリ受信開始エラー: {e}")
            return False

    def stop(self) -> None:
        """受信停止"""
        self._running = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        logger.info("テレメトリ受信停止")

    def _receive_loop(self) -> None:
        """受信ループ"""
        while self._running:
            try:
                if not self.sock:
                    break
                data, addr = self.sock.recvfrom(1024)
                state_str = data.decode('utf-8').strip()
                self._parse_state(state_str)
            except socket.timeout:
                continue
            except OSError:
                break
            except Exception as e:
                if self._running:
                    logger.error(f"テレメトリ受信エラー: {e}")

    def _parse_state(self, data: str) -> None:
        """
        テレメトリ文字列をパース。

        フォーマット例:
        pitch:0;roll:0;yaw:0;vgx:0;vgy:0;vgz:0;templ:56;temph:59;
        tof:6553;h:0;bat:87;baro:-42.07;time:0;agx:-12.00;agy:5.00;agz:-1000.00;
        """
        try:
            parsed = {}
            pairs = data.rstrip(';').split(';')
            for pair in pairs:
                if ':' in pair:
                    key, val = pair.split(':', 1)
                    parsed[key.strip()] = val.strip()

            self.state = parsed

            if self.on_state_update:
                self.on_state_update(self.get_formatted_state())

        except Exception as e:
            logger.debug(f"テレメトリパースエラー: {e}")

    def get_formatted_state(self) -> Dict[str, Any]:
        """整形されたステータスを返す"""
        s = self.state
        try:
            return {
                'pitch': int(s.get('pitch', 0)),
                'roll': int(s.get('roll', 0)),
                'yaw': int(s.get('yaw', 0)),
                'speed_x': int(s.get('vgx', 0)),
                'speed_y': int(s.get('vgy', 0)),
                'speed_z': int(s.get('vgz', 0)),
                'temp_low': int(s.get('templ', 0)),
                'temp_high': int(s.get('temph', 0)),
                'tof': int(s.get('tof', 0)),
                'height': int(s.get('h', 0)),
                'battery': int(s.get('bat', 0)),
                'barometer': float(s.get('baro', 0)),
                'flight_time': int(s.get('time', 0)),
                'accel_x': float(s.get('agx', 0)),
                'accel_y': float(s.get('agy', 0)),
                'accel_z': float(s.get('agz', 0)),
            }
        except (ValueError, TypeError):
            return self.state
