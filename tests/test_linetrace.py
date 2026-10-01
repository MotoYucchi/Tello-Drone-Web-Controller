"""
LineTrace Algorithm & Engine 単体テスト
"""

import pytest
import numpy as np
import cv2

from src.linetrace.algorithm import LineTraceAlgorithm
from src.linetrace.engine import LineTraceEngine, LineTraceParams


def create_test_image_with_line(line_type="straight"):
    """テスト用の合成画像を作成 (480x360, BGR)"""
    img = np.zeros((360, 480, 3), dtype=np.uint8)  # 黒背景

    if line_type == "straight":
        # 中央を垂直に走る赤色の線 (幅14px)
        # 赤色: BGR (0, 0, 255) -> HSV (0, 255, 255)
        cv2.line(img, (240, 360), (240, 100), (0, 0, 255), 14)

    elif line_type == "diagonal_right":
        # 右に傾いた赤色の線
        cv2.line(img, (200, 360), (320, 100), (0, 0, 255), 14)

    elif line_type == "corner_right":
        # 下部から垂直に上がり、途中で右へ90度直角に折れ曲がる線
        cv2.line(img, (240, 360), (240, 200), (0, 0, 255), 14)
        cv2.line(img, (240, 200), (400, 200), (0, 0, 255), 14)

    return img


def test_straight_line_detection_standard():
    """通常機体での直線検出テスト"""
    engine = LineTraceEngine()
    engine.apply_preset('red')
    engine.params.camera_mode = "standard"

    img = create_test_image_with_line("straight")
    result = engine.process_frame(img)

    assert result.detected is True
    # ほぼ画面中央(240px)付近で検出されること
    assert abs(result.center_x - 240) < 30
    # 直線なので角度はほぼ0度
    assert abs(result.angle_deg) < 15.0
    # 通常機体なので lr_value は 0
    assert result.lr_value == 0
    # 直進前進速度が出ていること
    assert result.forward_speed > 0


def test_straight_line_detection_downward():
    """改造機体 (ほぼ真下カメラ) での直線検出テスト"""
    engine = LineTraceEngine()
    engine.apply_preset('red')
    engine.params.camera_mode = "downward"

    img = create_test_image_with_line("straight")
    result = engine.process_frame(img)

    assert result.detected is True
    assert abs(result.center_x - 240) < 30
    assert abs(result.angle_deg) < 15.0
    assert result.forward_speed > 0


def test_diagonal_line_detection():
    """傾いた線の角度検出テスト"""
    engine = LineTraceEngine()
    engine.apply_preset('red')
    engine.params.camera_mode = "standard"

    img = create_test_image_with_line("diagonal_right")
    result = engine.process_frame(img)

    assert result.detected is True
    # 右傾きなので angle_deg > 0
    assert result.angle_deg > 5.0
    # 通常機体は右傾きに対して右旋回 (+yaw)
    assert result.yaw_value > 0


def test_corner_detection():
    """直角コーナー検出テスト"""
    engine = LineTraceEngine()
    engine.apply_preset('red')
    engine.params.camera_mode = "standard"

    img = create_test_image_with_line("corner_right")
    result = engine.process_frame(img)

    assert result.detected is True
    # コーナー判定が立っていること
    assert result.is_corner is True
    assert result.corner_dir == "right"
    # コーナーでの右旋回
    assert result.yaw_value > 0


def test_downward_mode_lateral_control():
    """改造機体での左右並進移動 (lr) 制御テスト"""
    engine = LineTraceEngine()
    engine.apply_preset('red')
    engine.params.camera_mode = "downward"
    engine.params.deadzone = 5.0

    # 右寄りの線 (x=300)
    img = np.zeros((360, 480, 3), dtype=np.uint8)
    cv2.line(img, (320, 360), (320, 100), (0, 0, 255), 14)

    result = engine.process_frame(img)
    assert result.detected is True
    # 右にずれているため lr > 0 (右へ並進)
    assert result.lr_value > 0


def test_color_presets():
    """色プリセットの切替テスト"""
    engine = LineTraceEngine()
    assert engine.apply_preset('blue') is True
    assert engine.params.h_min == 100
    assert engine.params.h_max == 130

    assert engine.apply_preset('yellow') is True
    assert engine.params.h_min == 20

    assert engine.apply_preset('invalid_color') is False


def test_curved_line_tracking():
    """くねくね（曲線/S字）の追跡テスト"""
    engine = LineTraceEngine()
    engine.apply_preset('red')
    engine.params.camera_mode = "standard"

    # くねくね曲線を短い線分の連続として描画
    img = np.zeros((360, 480, 3), dtype=np.uint8)
    pts = [
        (240, 360),
        (230, 310),
        (210, 260),
        (230, 210),
        (260, 160),
        (280, 110),
    ]
    for i in range(len(pts) - 1):
        cv2.line(img, pts[i], pts[i+1], (0, 0, 255), 14)

    result = engine.process_frame(img)
    assert result.detected is True
    assert result.forward_speed > 0


def test_noise_immunity():
    """背景に同系色の孤立ノイズが存在してもドローン手前の主ラインを追跡できるか検証"""
    engine = LineTraceEngine()
    engine.apply_preset('red')
    engine.params.camera_mode = "standard"

    img = np.zeros((360, 480, 3), dtype=np.uint8)
    # ドローン直近の主ライン (下部中央)
    cv2.line(img, (240, 360), (240, 220), (0, 0, 255), 14)

    # 画面上部・端に同系色のノイズ物体
    cv2.circle(img, (80, 50), 30, (0, 0, 255), -1)
    cv2.line(img, (40, 80), (120, 80), (0, 0, 255), 14)

    result = engine.process_frame(img)
    assert result.detected is True
    # 主ライン(x=240付近)を追跡していること (ノイズ物体 x=80 に引っ張られない)
    assert abs(result.center_x - 240) < 30

