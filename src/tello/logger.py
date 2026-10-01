"""
Tello Flight Logger — 飛行ログ (Timeline CSV) 記録

接続セッション毎に logs/TELLO_YYYY-MM-DD-HH-mm-ss.csv を自動生成し、
飛行時間をTimelineとして移動情報(RC値/コマンド)やバッテリー、高度、姿勢、
LineTrace状態をセットで記録する。
"""

import os
import csv
import time
import logging
import threading
from datetime import datetime
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


class FlightLogger:
    """Tello飛行ログ記録クラス"""

    CSV_HEADERS = [
        "timestamp",
        "elapsed_sec",
        "flight_time_sec",
        "battery_pct",
        "height_cm",
        "temp_low_c",
        "temp_high_c",
        "pitch_deg",
        "roll_deg",
        "yaw_deg",
        "speed_x_cms",
        "speed_y_cms",
        "speed_z_cms",
        "barometer_m",
        "tof_cm",
        "rc_lr",
        "rc_fb",
        "rc_ud",
        "rc_yaw",
        "control_mode",
        "lt_detected",
        "lt_center_x",
        "lt_center_y",
        "lt_offset_dx",
        "lt_angle_deg",
        "lt_is_corner",
        "event_note",
    ]

    def __init__(self, log_dir: str = "logs"):
        self.log_dir = log_dir
        self.is_logging = False
        self.current_file: Optional[str] = None
        self.start_time: float = 0.0
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # 最新データバッファ
        self._latest_telemetry: Dict[str, Any] = {}
        self._latest_rc: Dict[str, int] = {'lr': 0, 'fb': 0, 'ud': 0, 'yaw': 0}
        self._control_mode: str = "idle"  # idle, manual, linetrace
        self._latest_linetrace: Dict[str, Any] = {}
        self._event_queue: List[str] = []

        # ログディレクトリ作成
        os.makedirs(self.log_dir, exist_ok=True)

    def start_session(self) -> str:
        """新しい接続・飛行セッションのログ記録を開始"""
        with self._lock:
            if self.is_logging:
                self.stop_session()

            now_str = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
            filename = f"TELLO_{now_str}.csv"
            self.current_file = os.path.join(self.log_dir, filename)
            self.start_time = time.time()
            self._event_queue.clear()

            # CSVヘッダー書き込み (UTF-8 with BOM for Excel compatibility)
            try:
                with open(self.current_file, mode='w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.writer(f)
                    writer.writerow(self.CSV_HEADERS)
                logger.info(f"フライトログセッション開始: {self.current_file}")
            except Exception as e:
                logger.error(f"フライトログ作成エラー: {e}")
                self.current_file = None
                return ""

            self.is_logging = True
            self._thread = threading.Thread(target=self._log_loop, daemon=True, name="flight-logger")
            self._thread.start()
            return self.current_file

    def stop_session(self) -> Optional[str]:
        """ログ記録セッションを終了"""
        with self._lock:
            if not self.is_logging:
                return self.current_file

            self.is_logging = False
            last_file = self.current_file
            logger.info(f"フライトログセッション終了: {last_file}")
            return last_file

    def update_telemetry(self, state: Dict[str, Any]) -> None:
        """テレメトリ情報の更新"""
        with self._lock:
            self._latest_telemetry = state.copy()

    def update_rc(self, lr: int, fb: int, ud: int, yaw: int, mode: str = "manual") -> None:
        """RC制御値と制御モードの更新"""
        with self._lock:
            self._latest_rc = {'lr': lr, 'fb': fb, 'ud': ud, 'yaw': yaw}
            self._control_mode = mode

    def update_linetrace(self, result: Dict[str, Any]) -> None:
        """ライントレース結果の更新"""
        with self._lock:
            self._latest_linetrace = result.copy()

    def log_event(self, event_text: str) -> None:
        """イベント（離陸、着陸、QRスキャンなど）の記録"""
        with self._lock:
            self._event_queue.append(event_text)

    def _log_loop(self) -> None:
        """定期記録ループ (約1秒周期)"""
        while self.is_logging and self.current_file:
            try:
                self._record_row()
            except Exception as e:
                logger.error(f"ログ書き込みエラー: {e}")
            time.sleep(1.0)

    def _record_row(self) -> None:
        """1レコードをCSVに追記"""
        with self._lock:
            if not self.current_file:
                return

            now = datetime.now().isoformat()
            elapsed = round(time.time() - self.start_time, 2)
            tel = self._latest_telemetry
            rc = self._latest_rc
            lt = self._latest_linetrace
            event = "; ".join(self._event_queue)
            self._event_queue.clear()

            row = [
                now,
                elapsed,
                tel.get('flight_time', 0),
                tel.get('battery', 0),
                tel.get('height', 0),
                tel.get('temp_low', 0),
                tel.get('temp_high', 0),
                tel.get('pitch', 0),
                tel.get('roll', 0),
                tel.get('yaw', 0),
                tel.get('speed_x', 0),
                tel.get('speed_y', 0),
                tel.get('speed_z', 0),
                tel.get('barometer', 0.0),
                tel.get('tof', 0),
                rc.get('lr', 0),
                rc.get('fb', 0),
                rc.get('ud', 0),
                rc.get('yaw', 0),
                self._control_mode,
                lt.get('detected', False),
                lt.get('center_x', 0),
                lt.get('center_y', 0),
                lt.get('offset_dx', 0.0),
                lt.get('angle_deg', 0.0),
                lt.get('is_corner', False),
                event,
            ]

        with open(self.current_file, mode='a', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(row)

    def list_logs(self) -> List[Dict[str, Any]]:
        """保存済みログファイル一覧を取得"""
        if not os.path.exists(self.log_dir):
            return []

        files = []
        for fname in os.listdir(self.log_dir):
            if fname.startswith("TELLO_") and fname.endswith(".csv"):
                fpath = os.path.join(self.log_dir, fname)
                stat = os.stat(fpath)
                files.append({
                    "filename": fname,
                    "filepath": fpath,
                    "size_bytes": stat.st_size,
                    "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })
        # 新しい順にソート
        files.sort(key=lambda x: x["modified_time"], reverse=True)
        return files

    def get_latest_log_path(self) -> Optional[str]:
        """最新のログファイルパスを返す"""
        if self.current_file and os.path.exists(self.current_file):
            return self.current_file
        logs = self.list_logs()
        if logs:
            return logs[0]["filepath"]
        return None
