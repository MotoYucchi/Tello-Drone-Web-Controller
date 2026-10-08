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
        self._last_command_time = time.time()

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

            # ポート再利用を許可 (再接続時のポートバインド競合を回避)
            try:
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            except Exception:
                pass

            # Windows特有のWSAECONNRESET (10054: ICMP Port Unreachable) による受信スレッド停止を抑制
            if hasattr(socket, 'SIO_UDP_CONNRESET'):
                try:
                    self.sock.ioctl(socket.SIO_UDP_CONNRESET, False)
                except Exception:
                    pass

            # WiFi側インターフェースにバインド
            self.sock.bind((bind_addr, self.TELLO_PORT))

            # 受信スレッド開始
            self._recv_running = True
            self._recv_thread = threading.Thread(
                target=self._receive_loop, daemon=True, name='tello-recv'
            )
            self._recv_thread.start()

            # SDKモードへ切り替え (UDPパケットロスに備えて最大2回試行)
            resp = self.send_command('command', timeout=5.0)
            if resp is None or 'ok' not in resp.lower():
                time.sleep(0.3)
                logger.warning("初回command無応答のため再試行します...")
                resp = self.send_command('command', timeout=5.0)

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

    def disconnect(self, force: bool = True) -> bool:
        """
        Telloから切断。

        バッテリー切れや電源断、通信断時にタイムアウトで20秒以上フリーズするのを防ぐため、
        応答待機なしで安全・即座にリソースを解放する。
        """
        try:
            logger.info(f"Tello切断中... (force={force})")

            # 飛行中フラグが残っている場合、機体が生きていれば着陸できるようコマンドだけ非同期送信
            if self.is_flying and self.sock:
                try:
                    self.send_command_no_wait('land')
                except Exception:
                    pass

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
            self.is_connected = False
            self.is_flying = False
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
                self._last_command_time = time.time()
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
            self._last_command_time = time.time()
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
                elif 'ok' in resp.lower() or 'error' in resp.lower():
                    # 標準レスポンス
                    self._response = resp
                    self._response_event.set()
                elif ';' in resp and ':' in resp:
                    # ポート8889に混ざったテレメトリ文字列 → ステータス更新のみ行い、コマンド応答待機は解除しない
                    self._parse_state_data(resp)
                else:
                    # その他の応答
                    self._response = resp
                    self._response_event.set()

            except ConnectionResetError:
                # Windows特有のWSAECONNRESET: Tello未応答やICMP到達不能でもソケットは正常なので継続
                time.sleep(0.01)
                continue
            except (socket.timeout, TimeoutError):
                continue
            except OSError as e:
                # 明示的にクローズされた場合のみ終了
                if not self._recv_running or not self.sock:
                    break
                logger.debug(f"受信ソケットOSエラー(継続試行): {e}")
                time.sleep(0.05)
            except Exception as e:
                if self._recv_running:
                    logger.error(f"受信ループ例外: {e}")
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
            logger.info("未接続のため自動接続を試行中...")
            if not self.connect():
                logger.error("離陸不可: Telloに接続できませんでした")
                return False
        if self.is_flying:
            logger.warning("既に飛行中です")
            return True
        # RC制御スレッドが走っている場合は干渉を防ぐため一時停止
        self.stop_rc()
        # SDKコマンドモードを確実に有効化 (15秒アイドルによるSDKモード解除への対策)
        logger.info("SDKモード確認 (command 送信)...")
        self.send_command('command', timeout=3.0)
        time.sleep(0.1)
        logger.info("離陸コマンド(takeoff)送信中...")
        resp = self.send_command('takeoff', timeout=20.0)
        if (resp and 'ok' in resp.lower()) or self.status.get('height', 0) > 20:
            self.is_flying = True
            logger.info("離陸成功")
            return True
        logger.error(f"離陸失敗 (応答: {resp})")
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
        while self.rc_active:
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
        """KeepAliveループ: コマンドが一定時間途絶えた場合のみSDKモード維持のためcommandを安全送信"""
        while self._keepalive_running and self.is_connected:
            time.sleep(2.0)
            if not self._keepalive_running or not self.is_connected:
                break
            # 直近8秒以内にユーザー等のコマンド送信があった場合は送信不要
            if time.time() - self._last_command_time < 8.0:
                continue
            # 他のコマンド実行をブロックしないよう非ブロッキングでロックを取得
            acquired = self._command_lock.acquire(blocking=False)
            if acquired:
                try:
                    if self.sock and self.is_connected:
                        self._last_command_time = time.time()
                        self.sock.sendto(b'command', self.TELLO_ADDRESS)
                        logger.debug("KeepAlive: command 送信")
                except Exception:
                    pass
                finally:
                    self._command_lock.release()

    # =========================================================================
    # 映像制御
    # =========================================================================

    def stream_on(self) -> bool:
        """映像ストリーミング開始 (streamon + setfps low でパケットロスを低減)"""
        resp = self.send_command('streamon', timeout=10.0)
        success = resp is not None and 'ok' in resp.lower()
        if success:
            # ストリーミングFPSをlowに設定してWi-Fi帯域負荷とH.264デコード欠損(MBエラー)を低減
            time.sleep(0.3)
            self.set_fps('low')
        return success

    def stream_off(self, wait: bool = False) -> bool:
        """映像ストリーミング停止 (wait=Falseでノンブロッキング送信)"""
        if not self.sock or not self.is_connected:
            return True
        if not wait:
            self.send_command_no_wait('streamoff')
            return True
        resp = self.send_command('streamoff', timeout=3.0)
        return resp is not None and 'ok' in resp.lower()

    def set_fps(self, fps: str = 'low') -> bool:
        """FPS設定 (low, middle, high)"""
        resp = self.send_command(f'setfps {fps}', timeout=5.0)
        return resp is not None and 'ok' in resp.lower()
