"""
Tello Video Receiver — 映像ストリーム受信

OpenCV VideoCaptureを使用してTelloの映像ストリーム(port 11111)を受信する。
"""

import cv2
import threading
import time
import logging
import numpy as np
from typing import Optional, Callable, Tuple

logger = logging.getLogger(__name__)


class TelloVideoReceiver:
    """Tello映像受信クラス"""

    # Tello映像ストリームアドレス
    VIDEO_URL = 'udp://@0.0.0.0:11111?overrun_nonfatal=1&fifo_size=50000000'

    def __init__(self):
        self.cap: Optional[cv2.VideoCapture] = None
        self.streaming = False
        self._thread: Optional[threading.Thread] = None
        self._process_thread: Optional[threading.Thread] = None

        # フレーム管理
        self._current_frame: Optional[np.ndarray] = None
        self._latest_process_frame: Optional[np.ndarray] = None
        self._process_event = threading.Event()
        self._frame_lock = threading.Lock()

        # 映像設定
        self.frame_width = 640
        self.frame_height = 480
        self.jpeg_quality = 80

        # 低遅延・バッファ制御パラメータ
        self.low_latency_mode = True   # 低遅延優先モード
        self.drain_rate = 1            # キャプチャ毎の破棄フレーム数 (0〜3)

        # 統計
        self._frame_count = 0
        self._fps = 0
        self._last_fps_time = time.time()
        self._total_frames = 0
        self._dropped_frames = 0

        # コールバック（フレーム受信時に呼ばれる）
        self.on_frame: Optional[Callable[[np.ndarray], None]] = None

    def start(self) -> bool:
        """映像受信開始"""
        if self.streaming:
            return True

        try:
            logger.info("映像受信開始...")
            import os
            # FFmpegキャプチャオプションを環境変数に設定しパケットバッファを最適化
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "overrun_nonfatal;1|fifo_size;50000000|fflags;nobuffer|flags;low_delay"

            self.cap = cv2.VideoCapture(self.VIDEO_URL, cv2.CAP_FFMPEG)

            if not self.cap.isOpened():
                logger.error("VideoCapture オープン失敗")
                return False

            try:
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass

            self.streaming = True

            # 1. キャプチャループスレッド (最優先でUDPパケットを読み続けバッファ蓄積を防ぐ)
            self._thread = threading.Thread(
                target=self._capture_loop, daemon=True, name='tello-video-cap'
            )
            self._thread.start()

            # 2. 画像処理ワーカースレッド (LineTrace/QR処理をキャプチャと完全分離)
            self._process_thread = threading.Thread(
                target=self._process_loop, daemon=True, name='tello-video-proc'
            )
            self._process_thread.start()

            logger.info("映像受信開始成功 (低遅延デカップリングモード)")
            return True

        except Exception as e:
            logger.error(f"映像受信開始エラー: {e}")
            self.streaming = False
            return False

    def stop(self) -> None:
        """映像受信停止"""
        self.streaming = False
        self._process_event.set()
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
        with self._frame_lock:
            self._current_frame = None
            self._latest_process_frame = None
        logger.info("映像受信停止")

    def flush_buffer(self) -> int:
        """
        蓄積された古いフレームを即時ドロップし、現在届いている最新フレームに同期する。
        映像を切断・再接続することなく遅延を一瞬で解消する。
        """
        if not self.cap or not self.cap.isOpened():
            return 0
        dropped = 0
        try:
            # バッファ内の滞留フレームを grab() で高速スキップ
            for _ in range(8):
                if self.cap.grab():
                    dropped += 1
                else:
                    break
            self._dropped_frames += dropped
            # 最新のフレームをデコード
            ret, frame = self.cap.retrieve()
            if ret and frame is not None and frame.size > 0:
                if frame.shape[1] != self.frame_width or frame.shape[0] != self.frame_height:
                    frame = cv2.resize(frame, (self.frame_width, self.frame_height))
                with self._frame_lock:
                    self._current_frame = frame
                    self._latest_process_frame = frame
                self._process_event.set()
            logger.info(f"映像遅延リセット: {dropped}フレーム破棄して最新フレームに復帰")
        except Exception as e:
            logger.debug(f"遅延リセット例外: {e}")
        return dropped

    def set_latency_params(self, low_latency: bool, drain_rate: int = 1) -> None:
        """遅延補正パラメータを手動設定"""
        self.low_latency_mode = bool(low_latency)
        self.drain_rate = max(0, min(int(drain_rate), 4))
        logger.info(f"遅延パラメータ更新: low_latency={self.low_latency_mode}, drain_rate={self.drain_rate}")

    def _capture_loop(self) -> None:
        """映像キャプチャループ: 画像処理で一切ブロックされず最新フレームを取得"""
        while self.streaming:
            try:
                if not self.cap or not self.cap.isOpened():
                    break

                # 低遅延モード時、蓄積を防ぐため設定枚数分の古いフレームを grab でスキップ
                if self.low_latency_mode and self.drain_rate > 0:
                    for _ in range(self.drain_rate):
                        if not self.cap.grab():
                            break
                    ret, frame = self.cap.retrieve()
                else:
                    ret, frame = self.cap.read()

                if not ret or frame is None or frame.size == 0:
                    time.sleep(0.005)
                    continue

                # リサイズ
                if frame.shape[1] != self.frame_width or frame.shape[0] != self.frame_height:
                    frame = cv2.resize(frame, (self.frame_width, self.frame_height))

                # 最新フレームの更新と処理ワーカースレッドの起床
                with self._frame_lock:
                    self._current_frame = frame
                    self._latest_process_frame = frame
                self._process_event.set()

                # FPS計算
                self._frame_count += 1
                self._total_frames += 1
                now = time.time()
                if now - self._last_fps_time >= 1.0:
                    self._fps = self._frame_count
                    self._frame_count = 0
                    self._last_fps_time = now

            except Exception as e:
                if self.streaming:
                    logger.error(f"キャプチャエラー: {e}")
                time.sleep(0.05)

    def _process_loop(self) -> None:
        """画像処理ワーカースレッド: キャプチャループをブロックせず最新フレームのみを処理"""
        while self.streaming:
            try:
                self._process_event.wait(timeout=0.1)
                if not self.streaming:
                    break
                self._process_event.clear()

                frame_to_proc = None
                with self._frame_lock:
                    if self._latest_process_frame is not None:
                        frame_to_proc = self._latest_process_frame
                        self._latest_process_frame = None

                if frame_to_proc is not None and self.on_frame:
                    try:
                        self.on_frame(frame_to_proc)
                    except Exception as e:
                        logger.error(f"フレームコールバックエラー: {e}")

            except Exception as e:
                logger.debug(f"画像処理ワーカー例外: {e}")
                time.sleep(0.01)

    def get_frame(self) -> Optional[np.ndarray]:
        """最新フレームを取得"""
        with self._frame_lock:
            return self._current_frame.copy() if self._current_frame is not None else None

    def get_frame_jpeg(self) -> Optional[bytes]:
        """最新フレームをJPEGバイト列で取得"""
        frame = self.get_frame()
        if frame is None:
            return None
        try:
            params = [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality]
            ok, encoded = cv2.imencode('.jpg', frame, params)
            return encoded.tobytes() if ok else None
        except Exception as e:
            logger.error(f"JPEGエンコードエラー: {e}")
            return None

    def generate_mjpeg_frames(self):
        """MJPEG ストリーム生成器（StreamingResponse用）"""
        while self.streaming:
            try:
                jpeg = self.get_frame_jpeg()
                if jpeg:
                    yield (
                        b'--frame\r\n'
                        b'Content-Type: image/jpeg\r\n\r\n' + jpeg + b'\r\n'
                    )
                    time.sleep(0.033)
                else:
                    time.sleep(0.05)
            except GeneratorExit:
                break
            except Exception as e:
                logger.debug(f"mjpegストリーム生成例外: {e}")
                time.sleep(0.05)

    def set_quality(self, width: int, height: int, quality: int) -> None:
        """映像品質設定"""
        self.frame_width = max(160, min(width, 1920))
        self.frame_height = max(120, min(height, 1080))
        self.jpeg_quality = max(10, min(quality, 100))

    def get_stats(self) -> dict:
        """統計情報"""
        return {
            'streaming': self.streaming,
            'fps': self._fps,
            'total_frames': self._total_frames,
            'resolution': f'{self.frame_width}x{self.frame_height}',
            'quality': self.jpeg_quality,
            'low_latency': self.low_latency_mode,
            'drain_rate': self.drain_rate,
            'dropped_frames': self._dropped_frames,
        }
