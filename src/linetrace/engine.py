"""
LineTrace Engine — ライン追跡エンジン

LineSegmentDetector + HSV/ガウシアンフィルターを用いた高度なライントレースエンジン。
通常機体 (standard) と 改造機体 (downward) の制御モード切り替え、
直線・曲線・直角コーナー追従に対応。
"""

import cv2
import numpy as np
import logging
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass, field

from .algorithm import LineTraceAlgorithm

logger = logging.getLogger(__name__)


# 色プリセット定義
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
        'h_min': 20, 'h_max': 35,
        's_min': 100, 's_max': 255,
        'v_min': 100, 'v_max': 255,
    },
    'black': {
        'h_min': 0, 'h_max': 179,
        's_min': 0, 's_max': 60,
        'v_min': 0, 'v_max': 60,
    },
}


@dataclass
class LineTraceParams:
    """LineTraceパラメータ"""
    # 機体カメラモード: "standard" (通常機体: 前方微下向き) または "downward" (改造機体: ほぼ真下)
    camera_mode: str = "standard"

    # HSV色抽出範囲
    h_min: int = 0
    h_max: int = 179
    s_min: int = 0
    s_max: int = 255
    v_min: int = 0
    v_max: int = 255

    # フィルタリング
    gaussian_ksize: int = 5       # ガウシアンブラーのカーネルサイズ (奇数)
    kernel_size: int = 5          # モルフォロジーカーネルサイズ
    min_line_length: int = 15     # LSD検出線分の最小長 (ピクセル)

    # 制御パラメータ
    forward_speed: int = 15       # 基準前進速度 (0-100)
    deadzone: float = 20.0        # 不感帯 (ピクセル)
    yaw_limit: float = 60.0       # 旋回リミット (-100〜100)

    # ゲイン設定
    kp_yaw_standard: float = 0.35
    kd_yaw_standard: float = 0.40
    kp_lr_downward: float = 0.25
    kp_yaw_downward: float = 0.60

    # ROI設定 (通常機体)
    roi_top_ratio_standard: float = 0.50
    roi_bottom_ratio_standard: float = 0.95

    # ROI設定 (改造機体: ほぼ真下カメラ)
    roi_top_ratio_downward: float = 0.15
    roi_bottom_ratio_downward: float = 0.95

    # 処理画像サイズ
    process_width: int = 480
    process_height: int = 360


@dataclass
class LineTraceResult:
    """LineTrace処理結果"""
    detected: bool = False
    center_x: int = 0
    center_y: int = 0
    offset_dx: float = 0.0
    angle_deg: float = 0.0
    is_corner: bool = False
    corner_dir: str = 'none'
    forward_speed: int = 0
    lr_value: int = 0
    yaw_value: int = 0
    segments_count: int = 0
    # 処理済みデバッグ画像
    debug_frame: Optional[np.ndarray] = None


class LineTraceEngine:
    """ライン追跡エンジン"""

    def __init__(self):
        self.params = LineTraceParams()
        self.active = False
        self._last_result = LineTraceResult()
        self._prev_target: Optional[Tuple[float, float]] = None

    def set_params(self, params_dict: Dict[str, Any]) -> None:
        """パラメータ一括設定"""
        for key, val in params_dict.items():
            if hasattr(self.params, key):
                current_attr = getattr(self.params, key)
                target_type = type(current_attr)
                try:
                    setattr(self.params, key, target_type(val))
                except (ValueError, TypeError):
                    setattr(self.params, key, val)

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
        """現在のパラメータを辞書形式で返す"""
        return {
            'camera_mode': self.params.camera_mode,
            'h_min': self.params.h_min,
            'h_max': self.params.h_max,
            's_min': self.params.s_min,
            's_max': self.params.s_max,
            'v_min': self.params.v_min,
            'v_max': self.params.v_max,
            'gaussian_ksize': self.params.gaussian_ksize,
            'forward_speed': self.params.forward_speed,
            'deadzone': self.params.deadzone,
            'yaw_limit': self.params.yaw_limit,
            'active': self.active,
        }

    def process_frame(self, frame: np.ndarray) -> LineTraceResult:
        """
        フレームを処理してライン検出結果を返す。

        Args:
            frame: BGR画像 (numpy配列)

        Returns:
            LineTraceResult
        """
        result = LineTraceResult()
        p = self.params

        try:
            detected, info, debug = LineTraceAlgorithm.process_image(
                frame, p, prev_target=self._prev_target
            )

            result.detected = detected
            result.center_x = info['center_x']
            result.center_y = info['center_y']
            result.offset_dx = info['offset_dx']
            result.angle_deg = info['angle_deg']
            result.is_corner = info['is_corner']
            result.corner_dir = info['corner_dir']
            result.forward_speed = info['forward_speed']
            result.lr_value = info['lr_value']
            result.yaw_value = info['yaw_value']
            result.segments_count = info['segments_count']
            result.debug_frame = debug

            if detected:
                self._prev_target = (float(info['center_x']), float(info['center_y']))
            else:
                self._prev_target = None

        except Exception as e:
            logger.error(f"LineTrace処理エラー: {e}")

        self._last_result = result
        return result

    def get_rc_values(self, result: Optional[LineTraceResult] = None) -> Dict[str, int]:
        """
        LineTrace結果からRC制御値を算出。

        Returns:
            {'lr': lr_val, 'fb': fb_val, 'ud': 0, 'yaw': yaw_val}
        """
        r = result or self._last_result
        if not self.active or not r.detected:
            return {'lr': 0, 'fb': 0, 'ud': 0, 'yaw': 0}

        return {
            'lr': r.lr_value,
            'fb': r.forward_speed,
            'ud': 0,
            'yaw': r.yaw_value,
        }

    def get_last_result_info(self) -> Dict[str, Any]:
        """最後の処理結果のメタ情報（デバッグ画像を除く）"""
        r = self._last_result
        return {
            'detected': r.detected,
            'center_x': r.center_x,
            'center_y': r.center_y,
            'offset_dx': r.offset_dx,
            'angle_deg': r.angle_deg,
            'is_corner': r.is_corner,
            'corner_dir': r.corner_dir,
            'forward_speed': r.forward_speed,
            'lr_value': r.lr_value,
            'yaw_value': r.yaw_value,
            'segments_count': r.segments_count,
        }
