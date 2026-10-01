"""
LineTrace Algorithm — LineSegmentDetector + HSV/ガウシアンフィルターによる新アルゴリズム

- 前処理: リサイズ、ガウシアンフィルター平滑化、HSV色空間変換、inRange二値化、モルフォロジー演算
- 線検出: cv2.LineSegmentDetector (LSD) を利用
- 認識対象: 直線、くねくね(曲線)、直角コーナー
- 背景ノイズ対策: 画面下部(ドローン直近)から連続する主ラインを優先トラッキング
- 機体対応: 通常機体 (standard) と 改造機体 (downward: ほぼ真下カメラ) の2系統制御
"""

import cv2
import numpy as np
import math
import logging
from typing import Tuple, Optional, Any, List, Dict

logger = logging.getLogger(__name__)


class LineTraceAlgorithm:
    """LineSegmentDetectorを活用したライントレース画像処理アルゴリズム"""

    @staticmethod
    def process_image(
        frame: np.ndarray,
        params: Any,
        prev_target: Optional[Tuple[float, float]] = None
    ) -> Tuple[bool, Dict[str, Any], Optional[np.ndarray]]:
        """
        画像処理を実行し、ライン検出および制御パラメータを算出する。

        Args:
            frame: 入力画像 (BGR)
            params: LineTraceParams 設定オブジェクト
            prev_target: 前回フレームのターゲット座標 (x, y)

        Returns:
            Tuple[detected: bool, result_info: Dict[str, Any], debug_frame: Optional[np.ndarray]]
        """
        result_info = {
            'detected': False,
            'center_x': 0,
            'center_y': 0,
            'offset_dx': 0.0,
            'angle_deg': 0.0,
            'is_corner': False,
            'corner_dir': 'none',
            'forward_speed': 0,
            'lr_value': 0,
            'yaw_value': 0,
            'segments_count': 0,
        }

        try:
            if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
                return False, result_info, None

            # 極小・破損フレームの誤検出防止ガード (10x10未満は無効)
            if frame.shape[0] < 10 or frame.shape[1] < 10:
                return False, result_info, None

            # 1. リサイズ
            h_proc, w_proc = params.process_height, params.process_width
            resized = cv2.resize(frame, (w_proc, h_proc))

            # 2. 機体モードに応じたROI切り出し
            is_downward = (getattr(params, 'camera_mode', 'standard') == 'downward')
            if is_downward:
                roi_top = int(h_proc * getattr(params, 'roi_top_ratio_downward', 0.15))
                roi_bottom = int(h_proc * getattr(params, 'roi_bottom_ratio_downward', 0.95))
            else:
                roi_top = int(h_proc * getattr(params, 'roi_top_ratio_standard', 0.50))
                roi_bottom = int(h_proc * getattr(params, 'roi_bottom_ratio_standard', 0.95))

            roi_top = max(0, min(roi_top, h_proc - 10))
            roi_bottom = max(roi_top + 10, min(roi_bottom, h_proc))
            roi = resized[roi_top:roi_bottom, :]
            roi_h, roi_w = roi.shape[:2]

            # ROIが極端に小さい場合のクラッシュ防止ガード
            if roi.size == 0 or roi_h < 10 or roi_w < 10:
                return False, result_info, None

            # 3. ガウシアンフィルター平滑化 (OpenCVクラッシュ防止: 正の奇数かつROI寸法未満を厳守)
            ksize = getattr(params, 'gaussian_ksize', 5)
            if not isinstance(ksize, int) or ksize < 1:
                ksize = 5
            if ksize % 2 == 0:
                ksize += 1
            max_k = min(roi_h, roi_w)
            if max_k % 2 == 0:
                max_k -= 1
            ksize = max(1, min(ksize, max(1, max_k)))
            blurred = cv2.GaussianBlur(roi, (ksize, ksize), 0)

            # 4. HSV色空間変換 & 二値化マスク
            hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)
            lower = np.array([params.h_min, params.s_min, params.v_min], dtype=np.uint8)
            upper = np.array([params.h_max, params.s_max, params.v_max], dtype=np.uint8)

            # Hueの巡回 (h_min > h_max の場合、赤などの境界対応)
            if params.h_min > params.h_max:
                mask1 = cv2.inRange(hsv, np.array([params.h_min, params.s_min, params.v_min]), np.array([179, params.s_max, params.v_max]))
                mask2 = cv2.inRange(hsv, np.array([0, params.s_min, params.v_min]), np.array([params.h_max, params.s_max, params.v_max]))
                mask = cv2.bitwise_or(mask1, mask2)
            else:
                mask = cv2.inRange(hsv, lower, upper)

            # モルフォロジー演算 (Closingでライン内部の穴埋め・途切れ結合、Openingで微小ノイズ除去)
            morph_ksize = max(3, getattr(params, 'kernel_size', 5))
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (morph_ksize, morph_ksize))
            closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
            opened = cv2.morphologyEx(closed, cv2.MORPH_OPEN, kernel)

            # デバッグ画像用ベース
            debug = cv2.cvtColor(opened, cv2.COLOR_GRAY2BGR)

            # 5. LineSegmentDetector (LSD) による線分検出
            lsd = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD)
            lines, _, _, _ = lsd.detect(opened)

            valid_segments = []
            min_len = getattr(params, 'min_line_length', 15)

            if lines is not None and len(lines) > 0:
                for line in lines:
                    x1, y1, x2, y2 = line[0]
                    # 下から上へ向くように正規化 (y1 > y2)
                    if y1 < y2:
                        x1, y1, x2, y2 = x2, y2, x1, y1

                    length = math.hypot(x2 - x1, y2 - y1)
                    if length < min_len:
                        continue

                    # 角度: 真上が0度、右傾きが正(+deg)、左傾きが負(-deg)
                    dx = x2 - x1
                    dy = -(y2 - y1)  # 画像座標は下向き正なので反転
                    angle_deg = math.degrees(math.atan2(dx, dy))

                    valid_segments.append({
                        'p1': (x1, y1),
                        'p2': (x2, y2),
                        'length': length,
                        'angle': angle_deg,
                        'mid_x': (x1 + x2) / 2.0,
                        'mid_y': (y1 + y2) / 2.0,
                        'bottom_y': max(y1, y2),
                        'top_y': min(y1, y2),
                    })

            result_info['segments_count'] = len(valid_segments)

            # 線分が見つからない場合は未検出
            if not valid_segments:
                # 代替としてマスクの重心を探索
                M = cv2.moments(opened)
                if M['m00'] > 500:
                    cx = int(M['m10'] / M['m00'])
                    cy = int(M['m01'] / M['m00'])
                    result_info['detected'] = True
                    result_info['center_x'] = cx
                    result_info['center_y'] = cy
                    frame_cx = roi_w / 2.0
                    offset_dx = cx - frame_cx
                    result_info['offset_dx'] = offset_dx
                    # フォールバック制御値
                    LineTraceAlgorithm._calc_rc_fallback(result_info, params, is_downward, offset_dx, 0.0)
                    cv2.circle(debug, (cx, cy), 8, (0, 0, 255), -1)
                return result_info['detected'], result_info, debug

            # 6. 主ラインの選定 (ドローン直近の画面下部中央に近い線分を起点として追跡)
            frame_cx = roi_w / 2.0
            frame_cy = float(roi_h)

            def segment_score(seg):
                # 画面下部にあるほど高スコア (bottom_y が大きい)
                # 画面中央(X)に近いほど高スコア
                # 前回のターゲット位置があればそれに近いものを優遇
                dist_from_bottom = frame_cy - seg['bottom_y']
                dist_from_cx = abs(seg['mid_x'] - frame_cx)
                temporal_dist = 0.0
                if prev_target is not None:
                    temporal_dist = math.hypot(seg['mid_x'] - prev_target[0], seg['mid_y'] - prev_target[1])

                score = (seg['length'] * 2.0) - (dist_from_bottom * 1.5) - (dist_from_cx * 0.8) - (temporal_dist * 0.5)
                return score

            valid_segments.sort(key=segment_score, reverse=True)
            anchor = valid_segments[0]

            # 7. 直角コーナーの検出
            # アンカー線分の先端付近に、直交する線分(|角度差|が60°〜120°、かつ水平に近い)があるか
            is_corner = False
            corner_dir = 'none'
            corner_angle = 0.0

            for seg in valid_segments:
                if seg is anchor:
                    continue
                # 角度差 (約60°〜120° で直交)
                diff_angle = abs(seg['angle'] - anchor['angle'])
                if diff_angle > 180:
                    diff_angle = 360 - diff_angle

                # 水平に近い線分 (|angle| > 40°)
                if 50 <= diff_angle <= 130 and abs(seg['angle']) > 40:
                    # アンカー先端(p2)と候補線分の端点(p1またはp2)の最小距離
                    d1 = math.hypot(seg['p1'][0] - anchor['p2'][0], seg['p1'][1] - anchor['p2'][1])
                    d2 = math.hypot(seg['p2'][0] - anchor['p2'][0], seg['p2'][1] - anchor['p2'][1])
                    min_endpoint_dist = min(d1, d2)

                    # 端点がアンカー先端付近 (ROI高さの40%以内) にあればコーナーと判定
                    if min_endpoint_dist < (roi_h * 0.40):
                        is_corner = True
                        corner_angle = seg['angle']
                        # コーナーの方向 (アンカー先端に対して線分全体が右か左か)
                        corner_dir = 'right' if seg['mid_x'] > anchor['p2'][0] else 'left'
                        break

            # 8. 追従ターゲット (位置と角度) の算出
            # アンカー線分および前方に連続する線分群から合成
            connected_segs = [anchor]
            curr = anchor
            for seg in valid_segments:
                if seg is anchor:
                    continue
                # 先端間の距離が近く、角度差が45度以内の線分をつなぐ (くねくね対応)
                p_dist = math.hypot(seg['bottom_y'] - curr['top_y'], seg['mid_x'] - curr['p2'][0])
                diff_a = abs(seg['angle'] - curr['angle'])
                if diff_a > 180:
                    diff_a = 360 - diff_a
                if p_dist < (roi_h * 0.35) and diff_a < 50:
                    connected_segs.append(seg)
                    curr = seg

            # 重み付け平均ターゲット
            total_len = sum(s['length'] for s in connected_segs)
            if total_len > 1e-4 and not math.isnan(total_len):
                target_x = sum(s['mid_x'] * s['length'] for s in connected_segs) / total_len
                target_y = sum(s['mid_y'] * s['length'] for s in connected_segs) / total_len
                target_angle = sum(s['angle'] * s['length'] for s in connected_segs) / total_len
            else:
                target_x = anchor['mid_x']
                target_y = anchor['mid_y']
                target_angle = anchor['angle']

            # NaN / Inf 安全ガード
            if math.isnan(target_x) or math.isinf(target_x):
                target_x = frame_cx
            if math.isnan(target_y) or math.isinf(target_y):
                target_y = float(roi_h) / 2.0
            if math.isnan(target_angle) or math.isinf(target_angle):
                target_angle = 0.0

            target_x = max(0.0, min(float(roi_w), target_x))
            target_y = max(0.0, min(float(roi_h), target_y))

            offset_dx = target_x - frame_cx

            result_info['detected'] = True
            result_info['center_x'] = int(target_x)
            result_info['center_y'] = int(target_y + roi_top)
            result_info['offset_dx'] = float(offset_dx)
            result_info['angle_deg'] = float(target_angle)
            result_info['is_corner'] = is_corner
            result_info['corner_dir'] = corner_dir

            # 9. 機体タイプ別のRC制御値算出
            LineTraceAlgorithm._calc_rc_controls(result_info, params, is_downward, offset_dx, target_angle, is_corner, corner_dir)

            # 10. デバッグ画面描画 (安全クリッピング付き)
            # 検出されたすべての線分を細いグレーで描画
            for seg in valid_segments:
                p1 = (int(np.clip(seg['p1'][0], -100, roi_w + 100)), int(np.clip(seg['p1'][1], -100, roi_h + 100)))
                p2 = (int(np.clip(seg['p2'][0], -100, roi_w + 100)), int(np.clip(seg['p2'][1], -100, roi_h + 100)))
                cv2.line(debug, p1, p2, (100, 100, 100), 1)

            # 追跡対象の線分を緑太線で描画
            for seg in connected_segs:
                p1 = (int(np.clip(seg['p1'][0], -100, roi_w + 100)), int(np.clip(seg['p1'][1], -100, roi_h + 100)))
                p2 = (int(np.clip(seg['p2'][0], -100, roi_w + 100)), int(np.clip(seg['p2'][1], -100, roi_h + 100)))
                cv2.line(debug, p1, p2, (0, 255, 0), 3)

            # アンカー線分はシアンで強調
            p1_a = (int(np.clip(anchor['p1'][0], -100, roi_w + 100)), int(np.clip(anchor['p1'][1], -100, roi_h + 100)))
            p2_a = (int(np.clip(anchor['p2'][0], -100, roi_w + 100)), int(np.clip(anchor['p2'][1], -100, roi_h + 100)))
            cv2.line(debug, p1_a, p2_a, (255, 255, 0), 3)

            # ターゲット位置
            tx, ty = int(np.clip(target_x, 0, roi_w - 1)), int(np.clip(target_y, 0, roi_h - 1))
            cv2.drawMarker(debug, (tx, ty), (0, 0, 255), cv2.MARKER_CROSS, 20, 2)

            # 画面中心基準線
            cv2.line(debug, (int(frame_cx), 0), (int(frame_cx), roi_h), (255, 0, 0), 1)

            # 制御ベクトル矢印
            rad = math.radians(target_angle)
            arrow_len = 40
            ax = int(np.clip(tx + arrow_len * math.sin(rad), -500, roi_w + 500))
            ay = int(np.clip(ty - arrow_len * math.cos(rad), -500, roi_h + 500))
            cv2.arrowedLine(debug, (tx, ty), (ax, ay), (0, 165, 255), 2)

            # ステータス情報テキスト描画
            mode_text = f"MODE: {'DOWNWARD' if is_downward else 'STANDARD'}"
            status_text = f"dx:{offset_dx:.1f} ang:{target_angle:.1f}deg"
            rc_text = f"RC lr:{result_info['lr_value']} fb:{result_info['forward_speed']} yaw:{result_info['yaw_value']}"

            cv2.putText(debug, mode_text, (10, 20), cv2.FONT_HERSHEY_PLAIN, 1.1, (255, 255, 255), 1)
            cv2.putText(debug, status_text, (10, 40), cv2.FONT_HERSHEY_PLAIN, 1.0, (200, 255, 200), 1)
            cv2.putText(debug, rc_text, (10, 60), cv2.FONT_HERSHEY_PLAIN, 1.0, (0, 255, 255), 1)

            if is_corner:
                c_text = f"CORNER DETECTED: {corner_dir.upper()}"
                cv2.putText(debug, c_text, (10, 85), cv2.FONT_HERSHEY_PLAIN, 1.2, (0, 0, 255), 2)

            return True, result_info, debug

        except Exception as e:
            logger.error(f"LineTrace Algorithmエラー: {e}", exc_info=True)
            return False, result_info, None

    @staticmethod
    def _calc_rc_controls(
        result_info: Dict[str, Any],
        params: Any,
        is_downward: bool,
        offset_dx: float,
        target_angle: float,
        is_corner: bool,
        corner_dir: str
    ) -> None:
        """機体モードに応じたRC制御値(lr, fb, yaw)を計算"""
        base_speed = getattr(params, 'forward_speed', 15)
        deadzone = getattr(params, 'deadzone', 20.0)
        yaw_limit = getattr(params, 'yaw_limit', 60.0)

        # 不感帯の適用
        effective_dx = 0.0 if abs(offset_dx) < deadzone else offset_dx

        if is_downward:
            # =================================================================
            # 改造機体 (downward: ほぼ真下カメラ)
            # 真下にラインがあるため、横オフセットは左右移動(lr)でダイレクトに打ち消す
            # ヨー角(yaw)はラインの向き(target_angle)に機首をアライメントするために使う
            # =================================================================
            kp_lr = getattr(params, 'kp_lr_downward', 0.25)
            kp_yaw = getattr(params, 'kp_yaw_downward', 0.6)

            # 横移動 (正で右、負で左)
            lr = int(effective_dx * kp_lr)
            lr = max(-40, min(40, lr))

            # 旋回 (ラインの傾き角に合わせる)
            # target_angle: 右傾きが正 → 時計回り(cw:+yaw)で合わせる
            yaw = int(target_angle * kp_yaw)
            yaw = max(-int(yaw_limit), min(int(yaw_limit), yaw))

            # 前進速度: コーナー検出時は一旦停止・微速にして旋回/横移動を優先
            if is_corner:
                fb = 5
                if corner_dir == 'right':
                    yaw = 40
                    lr = 25
                elif corner_dir == 'left':
                    yaw = -40
                    lr = -25
            else:
                # 角度ズレやオフセットが大きい場合は前進を減速
                slowdown = min(1.0, max(0.2, 1.0 - (abs(target_angle) / 90.0) - (abs(effective_dx) / 200.0)))
                fb = max(5, int(base_speed * slowdown))

        else:
            # =================================================================
            # 通常機体 (standard: 前方微下向きカメラ)
            # ラインは正面下部に見えるため、主に前進(fb) + Yaw旋回で曲がる
            # lrは0または微小補正
            # =================================================================
            kp_yaw = getattr(params, 'kp_yaw_standard', 0.35)
            kd_yaw = getattr(params, 'kd_yaw_standard', 0.4)

            # Yaw: オフセット補正 + 角度先行制御
            # 画面右(offset_dx > 0)にラインがあるなら右旋回(+yaw)
            # ラインが右傾き(target_angle > 0)なら右旋回(+yaw)
            yaw = int((effective_dx * kp_yaw) + (target_angle * kd_yaw))
            yaw = max(-int(yaw_limit), min(int(yaw_limit), yaw))

            lr = 0

            if is_corner:
                fb = 5
                yaw = 50 if corner_dir == 'right' else -50
            else:
                # 旋回量が大きいときは前進を抑制してコースアウトを防止
                slowdown = max(0.2, 1.0 - (abs(yaw) / float(yaw_limit)))
                fb = max(5, int(base_speed * slowdown))

        result_info['forward_speed'] = int(fb)
        result_info['lr_value'] = int(lr)
        result_info['yaw_value'] = int(yaw)

    @staticmethod
    def _calc_rc_fallback(
        result_info: Dict[str, Any],
        params: Any,
        is_downward: bool,
        offset_dx: float,
        target_angle: float
    ) -> None:
        """フォールバック (モーメント重心のみ検出時) のRC値算出"""
        deadzone = getattr(params, 'deadzone', 20.0)
        base_speed = getattr(params, 'forward_speed', 10)
        effective_dx = 0.0 if abs(offset_dx) < deadzone else offset_dx

        if is_downward:
            lr = int(effective_dx * 0.2)
            result_info['lr_value'] = max(-30, min(30, lr))
            result_info['forward_speed'] = max(5, int(base_speed * 0.7))
            result_info['yaw_value'] = 0
        else:
            yaw = int(effective_dx * 0.3)
            result_info['lr_value'] = 0
            result_info['forward_speed'] = max(5, int(base_speed * 0.7))
            result_info['yaw_value'] = max(-50, min(50, yaw))
