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

        # フレーム管理
        self._current_frame: Optional[np.ndarray] = None
        self._frame_lock = threading.Lock()

        # 映像設定
        self.frame_width = 640
        self.frame_height = 480
        self.jpeg_quality = 80

        # 統計
        self._frame_count = 0
        self._fps = 0
        self._last_fps_time = time.time()
        self._total_frames = 0

        # コールバック（フレーム受信時に呼ばれる）
        self.on_frame: Optional[Callable[[np.ndarray], None]] = None

    def start(self) -> bool:
        """映像受信開始"""
        if self.streaming:
            return True

        try:
            logger.info("映像受信開始...")
            self.cap = cv2.VideoCapture(self.VIDEO_URL)

            if not self.cap.isOpened():
                logger.error("VideoCapture オープン失敗")
                return False

            self.streaming = True
            self._thread = threading.Thread(
                target=self._capture_loop, daemon=True, name='tello-video'
            )
            self._thread.start()
            logger.info("映像受信開始成功")
            return True

        except Exception as e:
            logger.error(f"映像受信開始エラー: {e}")
            self.streaming = False
            return False

    def stop(self) -> None:
        """映像受信停止"""
        self.streaming = False
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
        with self._frame_lock:
            self._current_frame = None
        logger.info("映像受信停止")

    def _capture_loop(self) -> None:
        """映像キャプチャループ"""
        while self.streaming:
            try:
                if not self.cap or not self.cap.isOpened():
                    break

                ret, frame = self.cap.read()
                if not ret or frame is None or frame.size == 0:
                    time.sleep(0.01)
                    continue

                # リサイズ
                if frame.shape[1] != self.frame_width or frame.shape[0] != self.frame_height:
                    frame = cv2.resize(frame, (self.frame_width, self.frame_height))

                with self._frame_lock:
                    self._current_frame = frame

                # フレームコールバック
                if self.on_frame:
                    try:
                        self.on_frame(frame)
                    except Exception as e:
                        logger.error(f"フレームコールバックエラー: {e}")

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
                time.sleep(0.1)

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
            jpeg = self.get_frame_jpeg()
            if jpeg:
                yield (
                    b'--frame\r\n'
                    b'Content-Type: image/jpeg\r\n\r\n' + jpeg + b'\r\n'
                )
            else:
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
        }
