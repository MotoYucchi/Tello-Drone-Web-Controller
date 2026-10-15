"""
LineTrace Engine — ライン追跡エンジン

LineSegmentDetector + HSV/ガウシアンフィルターを用いた高度なライントレースエンジン。
通常機体 (standard) と 改造機体 (downward) の制御モード切り替え、
直線・曲線・直角コーナー追従に対応。
"""

import cv2
import numpy as np
import logging
import collections
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
    forward_speed: int = 12       # 基準前進速度 (0-100, 初期値12でふらつきを防止)
    deadzone: float = 15.0        # 不感帯 (ピクセル, スムースランプ適用)
    yaw_limit: float = 35.0       # 旋回リミット (-100〜100, 急旋回・過回転を防止)
    lr_limit: float = 25.0        # 改造機体 横移動リミット

    # ゲイン設定 (ふらふら防止チューニング)
    kp_yaw_standard: float = 0.18 # 旋回Pゲイン (0.35から適正化しハンチングを排除)
    kd_yaw_standard: float = 0.25 # 角度先行Dゲイン
    kd_damping: float = 0.20      # オフセット速度ダンピング (オーバーシュート制動)
    kp_lr_downward: float = 0.16  # 改造機体 横移動Pゲイン
    kp_yaw_downward: float = 0.35 # 改造機体 旋回Pゲイン

    # スムージング & 自動復帰設定
    ema_alpha: float = 0.35       # EMA平滑化係数 (0.0〜1.0)
    auto_recovery: bool = True    # ラインロスト時の自動探索・復帰機能
    search_yaw_speed: int = 20    # 自動探索時の旋回速度
    corner_recovery_back_speed: int = 10 # 通常機体でコーナー/ロスト時の後退速度 (0〜48)
    corner_memory_sec: float = 10.0      # コーナー検出情報の保持時間 (秒, 1.0〜20.0)
    lost_auto_rotate: bool = False      # ロスト時のホバリングで360度自動旋回探索
    lost_backtrack: bool = False        # ロスト時に直前位置まで後退復帰 (非コーナー時も後退)

    # ROI設定 (通常機体)
    roi_top_ratio_standard: float = 0.50
    roi_bottom_ratio_standard: float = 0.95

    # ROI設定 (改造機体: ほぼ真下カメラ)
    roi_top_ratio_downward: float = 0.15
    roi_bottom_ratio_downward: float = 0.95

    # 処理画像サイズ
    process_width: int = 480
    process_height: int = 360

    # コース種別: "square" (四角コース: 4コーナーで1周) または "other" (その他・未定義)
    course_type: str = "square"


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
    tracking_state: str = 'tracking'  # 'tracking', 'stabilizing', 'searching', 'lost', 'idle'
    status_message: str = ''
    # コース・周回トラッキング
    course_type: str = 'square'
    lap_count: int = 0
    corner_pass_count: int = 0
    current_lap_sec: float = 0.0
    last_lap_sec: float = 0.0
    # 処理済みデバッグ画像
    debug_frame: Optional[np.ndarray] = None



class LineTraceEngine:
    """ライン追跡エンジン"""

    def __init__(self):
        self.params = LineTraceParams()
        self.active = False
        self._last_result = LineTraceResult()
        self._prev_target: Optional[Tuple[float, float]] = None

        # 制御平滑化・ダンピング用状態
        self._prev_offset_dx: Optional[float] = None
        self._prev_time: float = 0.0
        self._filtered_lr: float = 0.0
        self._filtered_fb: float = 0.0
        self._filtered_yaw: float = 0.0

        # ラインロスト・自動復帰用状態
        self._last_seen_time: float = 0.0
        self._last_seen_dx: float = 0.0
        self._last_seen_angle: float = 0.0
        self._last_corner_dir: str = 'none'

        # コーナー記憶メモリ (直前のフレームで上書き消去されない耐障害性バッファ)
        self._recent_corner_dir: str = 'none'
        self._last_corner_time: float = 0.0
        self._recent_dx_history = collections.deque(maxlen=30)
        self._recent_angle_history = collections.deque(maxlen=30)

        # コース・周回トラッキング (四角コース: 4つの直角コーナー通過で1周)
        self.lap_count: int = 0
        self.corner_pass_count: int = 0
        self.lap_start_time: float = 0.0
        self.current_lap_sec: float = 0.0
        self.last_lap_sec: float = 0.0
        self._last_corner_event_time: float = 0.0

    def reset_lap_metrics(self) -> None:
        """周回カウンターとラップタイムをリセット"""
        self.lap_count = 0
        self.corner_pass_count = 0
        self.lap_start_time = 0.0
        self.current_lap_sec = 0.0
        self.last_lap_sec = 0.0
        self._last_corner_event_time = 0.0
        logger.info("周回トラッキングデータをリセットしました")


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
            'kp_yaw_standard': self.params.kp_yaw_standard,
            'kd_damping': self.params.kd_damping,
            'auto_recovery': self.params.auto_recovery,
            'corner_recovery_back_speed': self.params.corner_recovery_back_speed,
            'corner_memory_sec': self.params.corner_memory_sec,
            'lost_auto_rotate': self.params.lost_auto_rotate,
            'lost_backtrack': self.params.lost_backtrack,
            'course_type': getattr(self.params, 'course_type', 'square'),
            'lap_count': self.lap_count,
            'corner_pass_count': self.corner_pass_count,
            'current_lap_sec': self.current_lap_sec,
            'last_lap_sec': self.last_lap_sec,
            'active': self.active,
        }


    def process_frame(self, frame: np.ndarray) -> LineTraceResult:
        """
        フレームを処理してライン検出結果を返す。
        ダンピング制動、EMA平滑化、およびラインロスト時の自動復帰スキャンを統合。

        Args:
            frame: BGR画像 (numpy配列)

        Returns:
            LineTraceResult
        """
        import time
        result = LineTraceResult()
        p = self.params

        now = time.time()
        dt = (now - self._prev_time) if self._prev_time > 0 else 0.033
        dt = max(0.01, min(0.2, dt))
        self._prev_time = now

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
            result.segments_count = info['segments_count']
            result.debug_frame = debug

            if detected:
                self._prev_target = (float(info['center_x']), float(info['center_y']))
                self._last_seen_time = now
                self._last_seen_dx = float(info['offset_dx'])
                self._last_seen_angle = float(info['angle_deg'])

                # コーナー方向の記憶:
                # 直前1〜2フレームで 'none' になっても、設定された保持時間(デフォルト10秒)だけ履歴を確実に保持する
                corner_dir = str(info.get('corner_dir', 'none'))
                memory_sec = getattr(p, 'corner_memory_sec', 10.0)
                if corner_dir in ('right', 'left'):
                    self._last_corner_dir = corner_dir
                    self._recent_corner_dir = corner_dir
                    self._last_corner_time = now
                elif (now - self._last_corner_time) > memory_sec:
                    self._recent_corner_dir = 'none'

                # 周回トラッキング (四角コース: 4つの直角コーナー通過で1周)
                if self.active:
                    if self.lap_start_time == 0.0:
                        self.lap_start_time = now

                    is_corner_now = bool(info.get('is_corner', False))
                    # コーナー検出かつ、前回のコーナーから2.5秒以上経過していれば新規コーナー通過と判定 (チャタリング防止)
                    if is_corner_now and (now - self._last_corner_event_time) > 2.5:
                        self._last_corner_event_time = now
                        self.corner_pass_count += 1
                        logger.info(f"コーナー通過検知: {self.corner_pass_count}/4 (直近方向: {self._recent_corner_dir})")

                        course_type = getattr(p, 'course_type', 'square')
                        if course_type == 'square':
                            if self.corner_pass_count >= 4:
                                self.lap_count += 1
                                self.last_lap_sec = round(now - self.lap_start_time, 2)
                                self.lap_start_time = now
                                self.corner_pass_count = 0
                                logger.info(f"★ 四角コース 1周完走！ Lap {self.lap_count}: {self.last_lap_sec}秒")

                self._recent_dx_history.append(float(info['offset_dx']))
                self._recent_angle_history.append(float(info['angle_deg']))


                is_first_detection = (self._prev_offset_dx is None)
                curr_dx = float(info['offset_dx'])
                if not is_first_detection and dt > 1e-4:
                    d_dx = (curr_dx - self._prev_offset_dx) / dt
                else:
                    d_dx = 0.0
                self._prev_offset_dx = curr_dx

                # 1. ダンピング項の算出 (PD制御: オフセット変化率による逆トルク制動)
                # 中央へ急速に戻っている時(d_dx < 0)は正の旋回を抑制(ブレーキ)し、オーバーシュートを防ぐ
                kd_damp = getattr(p, 'kd_damping', 0.015)
                damping_yaw = max(-15.0, min(15.0, d_dx * kd_damp))

                # 2. 基本指令値 (P項 + D項ダンピング適用とリミット)
                raw_yaw = float(info['yaw_value']) + damping_yaw
                yaw_limit = float(getattr(p, 'yaw_limit', 35.0))
                raw_yaw = max(-yaw_limit, min(yaw_limit, raw_yaw))

                raw_lr = float(info['lr_value'])
                if p.camera_mode == "downward":
                    damping_lr = max(-10.0, min(10.0, d_dx * 0.01))
                    raw_lr += damping_lr
                    lr_limit = float(getattr(p, 'lr_limit', 25.0))
                    raw_lr = max(-lr_limit, min(lr_limit, raw_lr))

                raw_fb = float(info['forward_speed'])

                # コーナー旋回中の追従能力向上:
                # 直近にコーナーを検知しており、まだ機首が新しいライン方向に十分に整っていない場合
                # 前進速度を抑え(fb <= 3)、コーナー方向への旋回を優先してコースアウト・通り過ぎを防止する
                had_recent_corner = (self._recent_corner_dir in ('right', 'left')) and ((now - self._last_corner_time) < memory_sec)
                if p.camera_mode == "standard" and had_recent_corner:
                    target_ang = abs(float(info.get('angle_deg', 0.0)))
                    target_dx = abs(float(info.get('offset_dx', 0.0)))
                    is_corner_now = bool(info.get('is_corner', False))
                    if is_corner_now or target_ang > 18.0 or target_dx > 35.0:
                        # まだコーナー検出中または旋回中
                        raw_fb = min(3.0, raw_fb)
                        corner_sign = 1.0 if self._recent_corner_dir == 'right' else -1.0
                        raw_yaw = corner_sign * max(abs(raw_yaw), min(yaw_limit, 35.0))
                    elif (now - self._last_corner_time) > 1.2:
                        # コーナー検知から時間が経過し、新ラインに完全に姿勢が整ったら解除
                        self._recent_corner_dir = 'none'

                # 3. EMA (指数移動平均) フィルタで高周波のふらつきを平滑化
                # 初回検出時は過去値がないためウォームスタートで即応性を確保
                alpha = getattr(p, 'ema_alpha', 0.35)
                if is_first_detection:
                    self._filtered_yaw = raw_yaw
                    self._filtered_lr = raw_lr
                    self._filtered_fb = raw_fb
                else:
                    self._filtered_yaw = alpha * raw_yaw + (1.0 - alpha) * self._filtered_yaw
                    self._filtered_lr = alpha * raw_lr + (1.0 - alpha) * self._filtered_lr
                    self._filtered_fb = alpha * raw_fb + (1.0 - alpha) * self._filtered_fb

                result.lr_value = int(round(self._filtered_lr))
                result.forward_speed = int(round(self._filtered_fb))
                result.yaw_value = int(round(self._filtered_yaw))
                result.tracking_state = 'tracking'
                result.status_message = 'ライン追従中'

            else:
                self._prev_target = None
                self._prev_offset_dx = None

                # ラインロスト時の処理
                if self.active and p.auto_recovery and self._last_seen_time > 0:
                    lost_sec = now - self._last_seen_time

                    # 直近にコーナー検知があったか (コーナーを通り過ぎた可能性が高いか)
                    memory_sec = getattr(p, 'corner_memory_sec', 10.0)
                    had_recent_corner = (self._recent_corner_dir in ('right', 'left')) and ((now - self._last_corner_time) < memory_sec)

                    if lost_sec < 0.4:
                        # Phase 1: 慣性減速・ホバリング安定化 (0.0s〜0.4s)
                        self._filtered_lr = 0.0
                        self._filtered_fb = 0.0
                        self._filtered_yaw = 0.0
                        result.lr_value = 0
                        result.forward_speed = 0
                        result.yaw_value = 0
                        result.tracking_state = 'stabilizing'
                        result.status_message = '姿勢安定化中 (ホバリング)'

                    elif lost_sec < 3.5:
                        # Phase 2: 直前見失い方向への自動スキャン探索 & 後退復帰 (0.4s〜3.5s)
                        # 判定優先順位: 1) 直近コーナー履歴, 2) 過去の平均傾き, 3) 最終dx
                        if had_recent_corner:
                            search_dir = 1 if self._recent_corner_dir == 'right' else -1
                        elif len(self._recent_angle_history) > 0 and abs(sum(self._recent_angle_history)) > 15.0:
                            avg_angle = sum(self._recent_angle_history) / len(self._recent_angle_history)
                            search_dir = 1 if avg_angle > 0 else -1
                        elif self._last_seen_dx > 5.0 or self._last_seen_angle > 5.0:
                            search_dir = 1
                        else:
                            search_dir = -1

                        search_speed = getattr(p, 'search_yaw_speed', 25)
                        dir_str = "右" if search_dir > 0 else "左"

                        if p.camera_mode == "downward":
                            # 改造機体 (ほぼ真下カメラ): 平行移動 + 旋回
                            result.lr_value = int(search_dir * 16)
                            result.yaw_value = int(search_dir * 12)
                            result.forward_speed = 0
                            result.status_message = f'自動探索: {dir_str}方向スキャン'
                        else:
                            # 通常機体 (前方微下向きカメラ):
                            result.lr_value = 0
                            result.yaw_value = int(search_dir * search_speed)

                            back_speed = getattr(p, 'corner_recovery_back_speed', 10)
                            back_speed = max(0, min(48, int(back_speed)))

                            if had_recent_corner:
                                # コーナーを通り過ぎた場合: 設定速度(最大48)で後退しながら旋回し、真下・後ろに抜けたラインを前方カメラ視野内に引き戻す
                                result.forward_speed = -back_speed
                                result.status_message = f'自動探索: コーナー復帰中 ({dir_str}旋回+微後退)'
                            elif getattr(p, 'lost_backtrack', False) and back_speed > 0:
                                # オプション: 全ロスト時の後退復帰 (ロスト前の位置まで後退)
                                result.forward_speed = -back_speed
                                result.status_message = f'自動探索: 直前位置へ後退中 ({dir_str}微スキャン)'
                            else:
                                result.forward_speed = 0
                                result.status_message = f'自動探索: {dir_str}方向スキャン'

                        result.tracking_state = 'searching'

                    elif lost_sec < 5.5:
                        # Phase 3: 探索継続 (コーナー記憶中はコーナー方向を維持、それ以外は反転スキャン)
                        if had_recent_corner:
                            search_dir = 1 if self._recent_corner_dir == 'right' else -1
                        elif self._last_seen_dx > 5.0 or self._last_seen_angle > 5.0:
                            search_dir = -1
                        else:
                            search_dir = 1

                        search_speed = getattr(p, 'search_yaw_speed', 25)
                        dir_str = "右" if search_dir > 0 else "左"

                        if p.camera_mode == "downward":
                            result.lr_value = int(search_dir * 14)
                            result.yaw_value = int(search_dir * 10)
                        else:
                            result.lr_value = 0
                            result.yaw_value = int(search_dir * search_speed)

                        result.forward_speed = 0
                        result.tracking_state = 'searching'
                        if had_recent_corner:
                            result.status_message = f'自動探索: {dir_str}旋回継続スキャン'
                        else:
                            result.status_message = f'自動探索: {dir_str}方向反転スキャン'

                    else:
                        # Phase 4: ロスト確定フェーズ (5.5s超)
                        if getattr(p, 'lost_auto_rotate', False):
                            # オプション: ロスト時ホバリング自動旋回モード (360°探索スキャン)
                            self._filtered_lr = 0.0
                            self._filtered_fb = 0.0
                            search_speed = getattr(p, 'search_yaw_speed', 20)
                            rotate_dir = 1 if (self._recent_corner_dir == 'right' or self._last_seen_dx >= 0) else -1
                            self._filtered_yaw = float(rotate_dir * search_speed)
                            result.lr_value = 0
                            result.forward_speed = 0
                            result.yaw_value = int(self._filtered_yaw)
                            result.tracking_state = 'searching'
                            dir_name = "右" if rotate_dir > 0 else "左"
                            result.status_message = f'自動探索: ホバリング自動旋回中 ({dir_name}360°スキャン)'
                        else:
                            # 通常: 完全ロスト・安全ホバリング待機 (5.5s超)
                            self._filtered_lr = 0.0
                            self._filtered_fb = 0.0
                            self._filtered_yaw = 0.0
                            result.lr_value = 0
                            result.forward_speed = 0
                            result.yaw_value = 0
                            result.tracking_state = 'lost'
                            result.status_message = 'ラインロスト: 安全ホバリング待機中'

                else:
                    # 初期状態または未追従時の未検出
                    self._filtered_lr = 0.0
                    self._filtered_fb = 0.0
                    self._filtered_yaw = 0.0
                    result.lr_value = 0
                    result.forward_speed = 0
                    result.yaw_value = 0
                    result.tracking_state = 'idle'
                    result.status_message = '未検出'

                # デバッグ画面に探索・ロスト状態をオーバーレイ描画
                if debug is not None and result.status_message:
                    h, w = debug.shape[:2]
                    color = (0, 255, 255) if result.tracking_state == 'searching' else (0, 0, 255)
                    cv2.putText(debug, result.status_message, (10, h - 20), cv2.FONT_HERSHEY_PLAIN, 1.2, color, 2)

                # 周回HUDオーバーレイ描画 (画面上部)
                if debug is not None:
                    c_type = getattr(p, 'course_type', 'square')
                    c_label = "SQUARE" if c_type == 'square' else "OTHER"
                    hud_text = f"[{c_label}] Lap: {self.lap_count} (C:{self.corner_pass_count}/4) Time:{self.current_lap_sec:.1f}s"
                    cv2.putText(debug, hud_text, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2)

        except Exception as e:
            logger.error(f"LineTrace処理エラー: {e}")

        # 周回情報をresultに反映
        self.current_lap_sec = round(now - self.lap_start_time, 2) if (self.active and self.lap_start_time > 0.0) else 0.0
        result.course_type = getattr(p, 'course_type', 'square')
        result.lap_count = self.lap_count
        result.corner_pass_count = self.corner_pass_count
        result.current_lap_sec = self.current_lap_sec
        result.last_lap_sec = self.last_lap_sec

        self._last_result = result
        return result


    def get_rc_values(self, result: Optional[LineTraceResult] = None) -> Dict[str, int]:
        """
        LineTrace結果からRC制御値を算出。

        Returns:
            {'lr': lr_val, 'fb': fb_val, 'ud': 0, 'yaw': yaw_val}
        """
        r = result or self._last_result
        if not self.active:
            return {'lr': 0, 'fb': 0, 'ud': 0, 'yaw': 0}

        # 安全確保: 前進(fb > 0)はライン検出中のみ許可。未検出時の前進暴走を防ぐ。
        # ただし通常機体のコーナー復帰探索における微後退(fb < 0)は許可する。
        if r.detected:
            fb = r.forward_speed
        else:
            fb = min(0, r.forward_speed)

        # ロスト・未追従・安定化中は全RCゼロ
        if not r.detected and r.tracking_state in ('lost', 'idle', 'stabilizing'):
            return {'lr': 0, 'fb': 0, 'ud': 0, 'yaw': 0}

        return {
            'lr': r.lr_value,
            'fb': fb,
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
            'tracking_state': r.tracking_state,
            'status_message': r.status_message,
            'course_type': r.course_type,
            'lap_count': r.lap_count,
            'corner_pass_count': r.corner_pass_count,
            'current_lap_sec': r.current_lap_sec,
            'last_lap_sec': r.last_lap_sec,
        }

