import cv2
import numpy as np
import logging
from typing import Tuple, Optional, Any

logger = logging.getLogger(__name__)

class LineTraceAlgorithm:
    """
    ライントレース用の画像処理アルゴリズム。
    HSVフィルタリング、ノイズ除去、重心算出などのロジックを担当。
    """
    
    @staticmethod
    def process_image(
        frame: np.ndarray,
        params: Any
    ) -> Tuple[bool, int, int, int, Tuple[int, int, int, int], Optional[np.ndarray]]:
        """
        画像処理を実行し、ラインを検出する。

        Args:
            frame: 入力画像(BGR)
            params: LineTraceParams (h_min, h_max, 等の設定を含む)

        Returns:
            Tuple[detected, center_x, center_y, area, bbox, debug_frame]
        """
        try:
            # (1) リサイズ
            small = cv2.resize(frame, (params.process_width, params.process_height))

            # (2) ROI切り出し（フレーム下部）
            h = small.shape[0]
            roi_top = int(h * params.roi_top_ratio)
            roi_bottom = int(h * params.roi_bottom_ratio)
            roi = small[roi_top:roi_bottom, :]

            # (3) HSV変換
            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

            # (4) inRange二値化
            lower = np.array([params.h_min, params.s_min, params.v_min])
            upper = np.array([params.h_max, params.s_max, params.v_max])
            binary = cv2.inRange(hsv, lower, upper)

            # (5) モルフォロジー変換（ノイズ除去と形状結合）
            kernel = np.ones((params.kernel_size, params.kernel_size), np.uint8)
            # Opening: 小さなノイズを除去
            opened = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
            # Closing: 途切れた線を繋ぐ
            closed = cv2.morphologyEx(opened, cv2.MORPH_CLOSE, kernel)
            # 膨張（より確実な結合）
            dilated = cv2.dilate(closed, kernel, iterations=1)

            # (6) マスク適用
            masked = cv2.bitwise_and(hsv, hsv, mask=dilated)

            # (7) ラベリング
            num_labels, label_img, stats, centers = cv2.connectedComponentsWithStats(dilated)

            # 背景(label 0)を除去
            num_labels -= 1
            if num_labels < 1:
                debug = cv2.cvtColor(masked, cv2.COLOR_HSV2BGR)
                return False, 0, 0, 0, (0, 0, 0, 0), debug

            stats = np.delete(stats, 0, 0)
            centers = np.delete(centers, 0, 0)

            # (8) 最大面積の領域を取得
            max_idx = np.argmax(stats[:, 4])
            x, y, w, h_box, s = stats[max_idx]
            mx = int(centers[max_idx][0])
            my = int(centers[max_idx][1])

            # デバッグ画像作成
            debug = cv2.cvtColor(masked, cv2.COLOR_HSV2BGR)
            cv2.rectangle(debug, (x, y), (x + w, y + h_box), (255, 0, 255), 2)
            cv2.putText(debug, f"area:{s}", (x, y + h_box + 15),
                        cv2.FONT_HERSHEY_PLAIN, 1, (0, 255, 255))
            cv2.drawMarker(debug, (mx, my), (0, 255, 0),
                           cv2.MARKER_CROSS, 20, 2)
            
            frame_center_x = roi.shape[1] // 2
            dx = float(frame_center_x - mx)
            yaw = 0.0 if abs(dx) < params.deadzone else -dx
            yaw = max(-params.yaw_limit, min(params.yaw_limit, yaw))
            
            cv2.arrowedLine(debug,
                            (frame_center_x, debug.shape[0] // 2),
                            (frame_center_x + int(yaw), debug.shape[0] // 2),
                            (0, 0, 255), 2)

            return True, mx, my, int(s), (int(x), int(y), int(w), int(h_box)), debug

        except Exception as e:
            logger.error(f"LineTrace Algorithmエラー: {e}")
            return False, 0, 0, 0, (0, 0, 0, 0), None
