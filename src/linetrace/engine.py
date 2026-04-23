"""
LineTrace Engine — ライン追跡エンジン

drone_linetrace_advanced.py から移植。
映像フレームからHSV色空間フィルタリングでラインを検出し、
その重心位置から旋回方向を算出してRC制御で追従する。

主要処理フロー:
1. フレーム取得 → リサイズ → ROI切り出し
2. HSV変換 → inRangeで二値化 → 膨張処理
3. connectedComponentsWithStats でラベリング
4. 最大面積領域の重心からyaw値を算出
5. rcコマンドで追従
"""

import cv2
import numpy as np
import logging
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# 色プリセット定義（drone_linetrace_advanced.py から移植）
COLOR_PRESETS: Dict[str, Dict[str, int]] = {
    'red': {
        'h_min': 0, 'h_max': 10,
        's_min': 100, 's_max': 255,
        'v_min': 100, 'v_max': 255,
    },
    'blue': {
        'h_min': 100, 'h_max': 130,
        's_min': 100, 's_max': 255,
        'v_min': 100, 'v_max': 255,
    },
    'yellow': {
        'h_min': 20, 'h_max': 30,
        's_min': 100, 's_max': 255,
        'v_min': 100, 'v_max': 255,
    },
    'black': {
        'h_min': 12, 'h_max': 40,
        's_min': 10, 's_max': 60,
        'v_min': 30, 'v_max': 50,
    },
}


@dataclass
class LineTraceParams:
    """LineTraceパラメータ"""
    # HSV範囲
    h_min: int = 0
    h_max: int = 179
    s_min: int = 0
    s_max: int = 255
    v_min: int = 0
    v_max: int = 255

    # 制御パラメータ
    forward_speed: int = 10       # 前進速度 (0-100)
    deadzone: float = 50.0        # 不感帯 (ピクセル)
    yaw_limit: float = 70.0       # 旋回リミット
    kernel_size: int = 15         # 膨張カーネルサイズ

    # ROI設定 (フレーム下部を注目領域とする)
    roi_top_ratio: float = 0.69   # ROI上端の比率 (250/360 ≈ 0.69)
    roi_bottom_ratio: float = 1.0 # ROI下端の比率

    # 処理画像サイズ
    process_width: int = 480
    process_height: int = 360


@dataclass
class LineTraceResult:
    """LineTrace処理結果"""
    detected: bool = False
    center_x: int = 0
    center_y: int = 0
    area: int = 0
    bbox: Tuple[int, int, int, int] = (0, 0, 0, 0)  # x, y, w, h
    yaw_value: float = 0.0
    forward_speed: int = 0
    # 処理済み画像（マスク+バウンディングボックス描画済み）
    debug_frame: Optional[np.ndarray] = None


class LineTraceEngine:
    """ライン追跡エンジン"""

    def __init__(self):
        self.params = LineTraceParams()
        self.active = False
        self._last_result = LineTraceResult()

    def set_params(self, params: Dict[str, Any]) -> None:
        """パラメータ一括設定"""
        for key, val in params.items():
            if hasattr(self.params, key):
                setattr(self.params, key, type(getattr(self.params, key))(val))

    def apply_preset(self, preset_name: str) -> bool:
        """色プリセット適用"""
        if preset_name not in COLOR_PRESETS:
            return False
        preset = COLOR_PRESETS[preset_name]
        self.params.h_min = preset['h_min']
        self.params.h_max = preset['h_max']
        self.params.s_min = preset['s_min']
        self.params.s_max = preset['s_max']
        self.params.v_min = preset['v_min']
        self.params.v_max = preset['v_max']
        logger.info(f"色プリセット適用: {preset_name}")
        return True

    def get_presets(self) -> Dict[str, Dict[str, int]]:
        """利用可能なプリセット一覧"""
        return COLOR_PRESETS.copy()

    def get_params(self) -> Dict[str, Any]:
        """現在のパラメータを返す"""
        return {
            'h_min': self.params.h_min,
            'h_max': self.params.h_max,
            's_min': self.params.s_min,
            's_max': self.params.s_max,
            'v_min': self.params.v_min,
            'v_max': self.params.v_max,
            'forward_speed': self.params.forward_speed,
            'deadzone': self.params.deadzone,
            'yaw_limit': self.params.yaw_limit,
            'kernel_size': self.params.kernel_size,
            'active': self.active,
        }

    def process_frame(self, frame: np.ndarray) -> LineTraceResult:
        """
        フレームを処理してライン検出結果を返す。

        drone_linetrace_advanced.py の処理を忠実に移植:
        1. リサイズ → ROI切り出し
        2. HSV変換 → inRange二値化 → 膨張
        3. ラベリング → 最大面積領域の重心取得
        4. 重心位置からyaw値算出

        Args:
            frame: BGR画像 (numpy配列)

        Returns:
            LineTraceResult
        """
        result = LineTraceResult()
        p = self.params

        try:
            # (1) リサイズ
            small = cv2.resize(frame, (p.process_width, p.process_height))

            # (2) ROI切り出し（フレーム下部）
            h = small.shape[0]
            roi_top = int(h * p.roi_top_ratio)
            roi_bottom = int(h * p.roi_bottom_ratio)
            roi = small[roi_top:roi_bottom, :]

            # (3) HSV変換
            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

            # (4) inRange二値化
            lower = np.array([p.h_min, p.s_min, p.v_min])
            upper = np.array([p.h_max, p.s_max, p.v_max])
            binary = cv2.inRange(hsv, lower, upper)

            # (5) 膨張処理（虎ロープなどの途切れを繋げる）
            kernel = np.ones((p.kernel_size, p.kernel_size), np.uint8)
            dilated = cv2.dilate(binary, kernel, iterations=1)

            # (6) マスク適用
            masked = cv2.bitwise_and(hsv, hsv, mask=dilated)

            # (7) ラベリング
            num_labels, label_img, stats, centers = cv2.connectedComponentsWithStats(dilated)

            # 背景(label 0)を除去
            num_labels -= 1
            if num_labels < 1:
                result.debug_frame = cv2.cvtColor(masked, cv2.COLOR_HSV2BGR)
                return result

            stats = np.delete(stats, 0, 0)
            centers = np.delete(centers, 0, 0)

            # (8) 最大面積の領域を取得
            max_idx = np.argmax(stats[:, 4])
            x, y, w, h_box, s = stats[max_idx]
            mx = int(centers[max_idx][0])
            my = int(centers[max_idx][1])

            result.detected = True
            result.center_x = mx
            result.center_y = my
            result.area = int(s)
            result.bbox = (int(x), int(y), int(w), int(h_box))

            # (9) yaw値算出（画面中心との差分）
            frame_center_x = roi.shape[1] // 2  # 240
            dx = float(frame_center_x - mx)

            # 不感帯
            yaw = 0.0 if abs(dx) < p.deadzone else -dx
            # リミッタ
            yaw = max(-p.yaw_limit, min(p.yaw_limit, yaw))

            result.yaw_value = yaw
            result.forward_speed = p.forward_speed

            # (10) デバッグ画像作成
            debug = cv2.cvtColor(masked, cv2.COLOR_HSV2BGR)
            cv2.rectangle(debug, (x, y), (x + w, y + h_box), (255, 0, 255), 2)
            cv2.putText(debug, f"area:{s}", (x, y + h_box + 15),
                        cv2.FONT_HERSHEY_PLAIN, 1, (0, 255, 255))
            cv2.drawMarker(debug, (mx, my), (0, 255, 0),
                           cv2.MARKER_CROSS, 20, 2)
            # yaw方向インジケーター
            cv2.arrowedLine(debug,
                            (frame_center_x, debug.shape[0] // 2),
                            (frame_center_x + int(yaw), debug.shape[0] // 2),
                            (0, 0, 255), 2)

            result.debug_frame = debug

        except Exception as e:
            logger.error(f"LineTrace処理エラー: {e}")

        self._last_result = result
        return result

    def get_rc_values(self, result: Optional[LineTraceResult] = None) -> Dict[str, int]:
        """
        LineTrace結果からRC制御値を算出。

        Returns:
            {'lr': 0, 'fb': forward_speed, 'ud': 0, 'yaw': yaw_value}
        """
        r = result or self._last_result
        if not self.active or not r.detected:
            return {'lr': 0, 'fb': 0, 'ud': 0, 'yaw': 0}

        return {
            'lr': 0,
            'fb': r.forward_speed,
            'ud': 0,
            'yaw': int(r.yaw_value),
        }

    def get_last_result_info(self) -> Dict[str, Any]:
        """最後の処理結果の情報（デバッグフレームを除く）"""
        r = self._last_result
        return {
            'detected': r.detected,
            'center_x': r.center_x,
            'center_y': r.center_y,
            'area': r.area,
            'bbox': list(r.bbox),
            'yaw_value': r.yaw_value,
            'forward_speed': r.forward_speed,
        }
