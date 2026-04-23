"""
Tello UDP Controller — 生UDPソケット通信

djitellopyを使わず、直接UDPソケットでTelloと通信する。
有線LAN + WiFi の同時接続環境でも、WiFi側インターフェースに
バインドすることで確実にTelloと通信可能。

Tello SDK仕様:
- コマンド送信: 192.168.10.1:8889 (UDP)
- テレメトリ受信: ローカルポート 8890 (UDP, Telloからの自動送信)
- 映像受信: ローカルポート 11111 (UDP)
- コマンドは順次実行（前のコマンド完了後に次を実行）
- 15秒間コマンドがないと自動着陸
"""

import socket
import subprocess
import threading
import time
import logging
import re
from typing import Optional, Callable, Dict, Any, Tuple

logger = logging.getLogger(__name__)


class TelloUDPController:
    """Telloドローンとの生UDP通信コントローラー"""

    TELLO_IP = '192.168.10.1'
    TELLO_PORT = 8889
    TELLO_ADDRESS = (TELLO_IP, TELLO_PORT)

    # Telloのサブネット
    TELLO_SUBNET_PREFIX = '192.168.10.'

    def __init__(self, local_ip: str = ''):
        """
        初期化

        Args:
            local_ip: バインドするローカルIP。空の場合は自動検出。
        """
        self.local_ip = local_ip
        self.sock: Optional[socket.socket] = None
        self.is_connected = False
        self.is_flying = False

        # レスポンス受信
        self._response: Optional[str] = None
        self._response_event = threading.Event()
        self._recv_thread: Optional[threading.Thread] = None
        self._recv_running = False

        # ステータス情報
        self.status = {
            'battery': 0,
            'flight_time': 0,
            'height': 0,
            'temperature': 0,
            'wifi_signal': 0,
        }

        # KeepAlive
        self._keepalive_thread: Optional[threading.Thread] = None
        self._keepalive_running = False

        # コマンドロック（順次実行を保証）
        self._command_lock = threading.Lock()

        # コールバック
        self.on_status_update: Optional[Callable[[Dict[str, Any]], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None

        # RC制御
        self.rc_active = False
        self._rc_thread: Optional[threading.Thread] = None
        self._rc_values = {'lr': 0, 'fb': 0, 'ud': 0, 'yaw': 0}

    # =========================================================================
    # ネットワークインターフェース検出
    # =========================================================================

    @staticmethod
    def find_tello_interface() -> str:
        """
        Telloのサブネット(192.168.10.x)に属するローカルIPアドレスを自動検出。

        Windows の `ipconfig` を解析し、192.168.10.x のアドレスを返す。
        見つからない場合は空文字を返す。
        """
        try:
            result = subprocess.run(
                ['ipconfig'],
                capture_output=True, text=True, encoding='cp932',
                timeout=5
            )
            # IPv4アドレスの行を検索
            pattern = r'IPv4.*?:\s*(192\.168\.10\.\d+)'
            matches = re.findall(pattern, result.stdout)
            if matches:
                ip = matches[0]
                logger.info(f"Telloインターフェース検出: {ip}")
                return ip
            else:
                logger.warning("Telloサブネットのインターフェースが見つかりません")
                return ''
        except Exception as e:
            logger.error(f"インターフェース検出エラー: {e}")
            return ''

    @staticmethod
    def list_network_interfaces() -> list[Dict[str, str]]:
        """利用可能なネットワークインターフェース一覧を返す"""
        interfaces = []
        try:
            result = subprocess.run(
                ['ipconfig'],
                capture_output=True, text=True, encoding='cp932',
                timeout=5
            )
            current_adapter = ""
            for line in result.stdout.splitlines():
                # アダプター名を検出
                adapter_match = re.match(r'^(.+?(?:アダプター|adapter))\s+(.+?):', line, re.IGNORECASE)
                if adapter_match:
                    current_adapter = adapter_match.group(2).strip()
                # IPv4アドレスを検出
                ip_match = re.search(r'IPv4.*?:\s*(\d+\.\d+\.\d+\.\d+)', line)
                if ip_match and current_adapter:
                    interfaces.append({
                        'adapter': current_adapter,
                        'ip': ip_match.group(1),
                        'is_tello': ip_match.group(1).startswith('192.168.10.')
                    })
        except Exception as e:
            logger.error(f"インターフェース一覧取得エラー: {e}")
        return interfaces

    # =========================================================================
    # 接続管理
    # =========================================================================

    def connect(self) -> bool:
        """Telloに接続（SDKモード開始）"""
        try:
            # ローカルIPが未指定なら自動検出
            if not self.local_ip:
                self.local_ip = self.find_tello_interface()

            bind_addr = self.local_ip or ''
            logger.info(f"UDP ソケット作成: bind=({bind_addr}, {self.TELLO_PORT})")

            # ソケット作成
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.settimeout(10.0)

            # WiFi側インターフェースにバインド
            self.sock.bind((bind_addr, self.TELLO_PORT))

            # 受信スレッド開始
            self._recv_running = True
            self._recv_thread = threading.Thread(
                target=self._receive_loop, daemon=True, name='tello-recv'
            )
            self._recv_thread.start()

            # SDKモードへ切り替え
            resp = self.send_command('command', timeout=10.0)
            if resp is None or 'ok' not in resp.lower():
                logger.error(f"SDKモード開始失敗: resp={resp}")
                self.disconnect()
                return False

            self.is_connected = True
            logger.info("Tello接続成功")

            # KeepAliveスレッド開始
            self._start_keepalive()

            # 初回ステータス取得
            self._query_status()

            return True

        except Exception as e:
            logger.error(f"Tello接続エラー: {e}")
            if self.on_error:
                self.on_error(f"接続エラー: {e}")
            self.disconnect()
            return False

    def disconnect(self) -> bool:
        """Telloから切断"""
        try:
            logger.info("Tello切断中...")

            # 飛行中なら着陸
            if self.is_flying:
                self.land()
                time.sleep(3)

            # RC制御停止
            self.stop_rc()

            # KeepAlive停止
            self._keepalive_running = False

            # 受信スレッド停止
            self._recv_running = False

            # ソケットクローズ
            if self.sock:
                try:
                    self.sock.close()
                except Exception:
                    pass
                self.sock = None

            self.is_connected = False
            self.is_flying = False
            logger.info("Tello切断完了")
            return True

        except Exception as e:
            logger.error(f"Tello切断エラー: {e}")
            return False

    # =========================================================================
    # コマンド送受信
    # =========================================================================

    def send_command(self, command: str, timeout: float = 7.0) -> Optional[str]:
        """
        コマンドを送信し、レスポンスを待つ。

        Telloはコマンドを1つずつ順次実行するため、
        コマンドロックで排他制御する。

        Args:
            command: 送信するコマンド文字列
            timeout: レスポンス待機タイムアウト（秒）

        Returns:
            レスポンス文字列。タイムアウトした場合はNone。
        """
        if not self.sock:
            logger.error("ソケットが未作成です")
            return None

        with self._command_lock:
            try:
                self._response = None
                self._response_event.clear()

                # 送信
                self.sock.sendto(
                    command.encode('utf-8'),
                    self.TELLO_ADDRESS
                )
                logger.debug(f"送信: {command}")

                # レスポンス待ち
                if self._response_event.wait(timeout=timeout):
                    resp = self._response
                    logger.debug(f"受信: {resp}")
                    return resp
                else:
                    logger.warning(f"タイムアウト: {command}")
                    return None

            except Exception as e:
                logger.error(f"コマンド送信エラー: {command} -> {e}")
                return None

    def send_command_no_wait(self, command: str) -> None:
        """コマンドを送信（レスポンスを待たない）。RC制御用。"""
        if not self.sock:
            return
        try:
            self.sock.sendto(
                command.encode('utf-8'),
                self.TELLO_ADDRESS
            )
        except Exception as e:
            logger.error(f"コマンド送信エラー(no_wait): {e}")

    def _receive_loop(self) -> None:
        """UDP受信ループ"""
        logger.info("受信スレッド開始")
        while self._recv_running:
            try:
                if not self.sock:
                    break
                data, addr = self.sock.recvfrom(2048)
                resp = data.decode('utf-8').strip()

                # レスポンスの種類を判定
                if resp.isdecimal():
                    # 数字のみ → バッテリー残量の応答
                    self.status['battery'] = int(resp)
                    self._response = resp
                    self._response_event.set()
                elif resp.endswith('s') and resp[:-1].isdecimal():
                    # "XXs" → 飛行時間の応答
                    self.status['flight_time'] = int(resp[:-1])
                    self._response = resp
                    self._response_event.set()
                elif resp.lower() in ('ok', 'error'):
                    # 標準レスポンス
                    self._response = resp
                    self._response_event.set()
                elif 'error' in resp.lower():
                    self._response = resp
                    self._response_event.set()
                else:
                    # その他（テレメトリデータなど）
                    self._parse_state_data(resp)
                    self._response = resp
                    self._response_event.set()

            except socket.timeout:
                continue
            except OSError:
                # ソケットが閉じられた
                break
            except Exception as e:
                if self._recv_running:
                    logger.error(f"受信エラー: {e}")
                time.sleep(0.1)

        logger.info("受信スレッド終了")

    def _parse_state_data(self, data: str) -> None:
        """テレメトリ文字列をパース (例: 'pitch:0;roll:0;yaw:0;...')"""
        try:
            pairs = data.split(';')
            for pair in pairs:
                if ':' in pair:
                    key, val = pair.split(':', 1)
                    key = key.strip()
                    val = val.strip()
                    if key == 'bat':
                        self.status['battery'] = int(val)
                    elif key == 'h':
                        self.status['height'] = int(val)
                    elif key == 'templ' or key == 'temph':
                        self.status['temperature'] = int(val)
                    elif key == 'time':
                        self.status['flight_time'] = int(val)

            if self.on_status_update:
                self.on_status_update(self.get_status())
        except Exception as e:
            logger.debug(f"ステートデータパースエラー: {e}")

    # =========================================================================
    # 飛行制御コマンド
    # =========================================================================

    def takeoff(self) -> bool:
        """離陸"""
        if not self.is_connected:
            return False
        if self.is_flying:
            logger.warning("既に飛行中です")
            return True
        resp = self.send_command('takeoff', timeout=20.0)
        if resp and 'ok' in resp.lower():
            self.is_flying = True
            logger.info("離陸成功")
            return True
        logger.error(f"離陸失敗: {resp}")
        return False

    def land(self) -> bool:
        """着陸"""
        if not self.is_connected:
            return False
        self.stop_rc()
        resp = self.send_command('land', timeout=15.0)
        if resp and 'ok' in resp.lower():
            self.is_flying = False
            logger.info("着陸成功")
            return True
        logger.error(f"着陸失敗: {resp}")
        return False

    def emergency(self) -> bool:
        """緊急停止（モーター即停止）"""
        if not self.is_connected:
            return False
        self.stop_rc()
        self.send_command_no_wait('emergency')
        self.is_flying = False
        logger.warning("緊急停止実行")
        return True

    def move(self, direction: str, distance: int = 30) -> bool:
        """
        移動コマンド

        Args:
            direction: forward, back, left, right, up, down
            distance: 20〜500 cm
        """
        if not self.is_flying:
            return False
        distance = max(20, min(distance, 500))
        resp = self.send_command(f'{direction} {distance}', timeout=15.0)
        return resp is not None and 'ok' in resp.lower()

    def rotate(self, direction: str, angle: int = 90) -> bool:
        """
        回転コマンド

        Args:
            direction: cw (時計回り), ccw (反時計回り)
            angle: 1〜360度
        """
        if not self.is_flying:
            return False
        angle = max(1, min(angle, 360))
        resp = self.send_command(f'{direction} {angle}', timeout=10.0)
        return resp is not None and 'ok' in resp.lower()

    def set_speed(self, speed: int = 50) -> bool:
        """速度設定 (10〜100 cm/s)"""
        if not self.is_connected:
            return False
        speed = max(10, min(speed, 100))
        resp = self.send_command(f'speed {speed}')
        return resp is not None and 'ok' in resp.lower()

    # =========================================================================
    # RC制御（リアルタイム連続制御）
    # =========================================================================

    def set_rc(self, lr: int = 0, fb: int = 0, ud: int = 0, yaw: int = 0) -> None:
        """RC制御値設定 (-100〜100)"""
        self._rc_values = {
            'lr': max(-100, min(lr, 100)),
            'fb': max(-100, min(fb, 100)),
            'ud': max(-100, min(ud, 100)),
            'yaw': max(-100, min(yaw, 100)),
        }

    def start_rc(self) -> None:
        """RC制御ループ開始"""
        if self.rc_active:
            return
        self.rc_active = True
        self._rc_thread = threading.Thread(
            target=self._rc_loop, daemon=True, name='tello-rc'
        )
        self._rc_thread.start()

    def stop_rc(self) -> None:
        """RC制御ループ停止"""
        self.rc_active = False
        self._rc_values = {'lr': 0, 'fb': 0, 'ud': 0, 'yaw': 0}
        if self.is_connected and self.sock:
            self.send_command_no_wait('rc 0 0 0 0')

    def _rc_loop(self) -> None:
        """RC制御値を50ms間隔で送信"""
        while self.rc_active and self.is_flying:
            v = self._rc_values
            cmd = f"rc {v['lr']} {v['fb']} {v['ud']} {v['yaw']}"
            self.send_command_no_wait(cmd)
            time.sleep(0.05)

    # =========================================================================
    # ステータスクエリ
    # =========================================================================

    def _query_status(self) -> None:
        """バッテリー・飛行時間を問い合わせ"""
        try:
            resp = self.send_command('battery?', timeout=5.0)
            if resp and resp.isdecimal():
                self.status['battery'] = int(resp)

            resp = self.send_command('time?', timeout=5.0)
            if resp and resp.endswith('s'):
                self.status['flight_time'] = int(resp[:-1])
        except Exception as e:
            logger.error(f"ステータスクエリエラー: {e}")

    def get_status(self) -> Dict[str, Any]:
        """現在のステータスを返す"""
        return {
            'connected': self.is_connected,
            'flying': self.is_flying,
            'battery': self.status['battery'],
            'height': self.status['height'],
            'temperature': self.status['temperature'],
            'flight_time': self.status['flight_time'],
            'local_ip': self.local_ip,
        }

    # =========================================================================
    # KeepAlive
    # =========================================================================

    def _start_keepalive(self) -> None:
        """5秒ごとにcommandを送信して死活チェック"""
        self._keepalive_running = True
        self._keepalive_thread = threading.Thread(
            target=self._keepalive_loop, daemon=True, name='tello-keepalive'
        )
        self._keepalive_thread.start()

    def _keepalive_loop(self) -> None:
        """KeepAliveループ"""
        while self._keepalive_running and self.is_connected:
            time.sleep(5.0)
            if self._keepalive_running and self.is_connected:
                try:
                    self.send_command_no_wait('command')
                    # ステータスも定期取得
                    self.send_command_no_wait('battery?')
                except Exception:
                    pass

    # =========================================================================
    # 映像制御
    # =========================================================================

    def stream_on(self) -> bool:
        """映像ストリーミング開始"""
        resp = self.send_command('streamon', timeout=10.0)
        return resp is not None and 'ok' in resp.lower()

    def stream_off(self) -> bool:
        """映像ストリーミング停止"""
        resp = self.send_command('streamoff', timeout=5.0)
        return resp is not None and 'ok' in resp.lower()

    def set_fps(self, fps: str = 'low') -> bool:
        """FPS設定 (low, middle, high)"""
        resp = self.send_command(f'setfps {fps}')
        return resp is not None and 'ok' in resp.lower()
