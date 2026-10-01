"""
安全性・フェイルセーフ・緊急停止に関するテストスイート
"""

import pytest
import numpy as np
from fastapi.testclient import TestClient

from src.server.app import app, app_state
from src.linetrace.algorithm import LineTraceAlgorithm
from src.linetrace.engine import LineTraceEngine, LineTraceParams
from src.tello.udp_controller import TelloUDPController


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_emergency_stops_linetrace_and_rc(client):
    """
    安全性テスト 1: 緊急停止 (REST API)
    LineTrace実行中に緊急停止が発令された場合、
    LineTraceが即時停止(active=False)し、飛行フラグが解除されること。
    """
    tello = app_state['tello']
    lt = app_state['linetrace']

    # 疑似的に接続・飛行・LineTrace稼働状態にする
    tello.is_connected = True
    tello.is_flying = True
    lt.active = True
    tello.rc_active = True
    tello.set_rc(10, 20, 0, 30)

    # 緊急停止を実行
    resp = client.post("/api/emergency")
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    # 安全状態の検証
    assert lt.active is False, "緊急停止後にLineTraceが有効なままです"
    assert tello.is_flying is False, "緊急停止後にis_flyingがTrueのままです"
    assert tello.rc_active is False, "緊急停止後にRC制御ループが動作したままです"
    assert tello._rc_values == {'lr': 0, 'fb': 0, 'ud': 0, 'yaw': 0}, "RC値がクリアされていません"


def test_land_stops_linetrace_and_rc(client):
    """
    安全性テスト 2: 着陸要求時のLineTrace停止
    LineTrace中に着陸コマンドが送られた場合、
    LineTraceが即時停止し、RC値がゼロリセットされること。
    """
    tello = app_state['tello']
    lt = app_state['linetrace']

    tello.is_connected = True
    tello.is_flying = True
    lt.active = True
    tello.rc_active = True
    tello.set_rc(0, 15, 0, 10)

    # 着陸要求
    # UDP未接続なのでsend_commandはNoneを返すが、前処理でlt.activeがFalseになることを確認
    resp = client.post("/api/land")
    assert lt.active is False, "着陸要求時にLineTraceが停止していません"
    assert tello.rc_active is False, "着陸要求時にRC制御が停止していません"


def test_line_loss_failsafe_stops_drone():
    """
    安全性テスト 3: ラインロスト(見失い)時の即時停止(ホバリング)
    ラインが検出されないフレームが入力された場合、
    前進速度および旋回・横移動がすべてゼロクリアされ、その場でホバリング静止すること。
    """
    engine = LineTraceEngine()
    engine.apply_preset('red')
    engine.active = True

    # ラインが全くない真っ黒な画像
    blank_frame = np.zeros((360, 480, 3), dtype=np.uint8)
    result = engine.process_frame(blank_frame)

    assert result.detected is False
    # RC制御値の確認
    rc = engine.get_rc_values(result)
    assert rc['fb'] == 0, "ライン見失い時に前進速度がゼロになっていません (暴走リスク)"
    assert rc['lr'] == 0, "ライン見失い時に横移動値が残っています"
    assert rc['yaw'] == 0, "ライン見失い時に旋回値が残っています"


def test_rc_values_strict_clamp():
    """
    安全性テスト 4: RC値・リミッタの厳格なクランプ
    過大な指令値や異常値が指定された場合でも、
    Tello SDK許容範囲 (-100〜100) および 設定リミッタ (yaw_limit等) を厳守すること。
    """
    tello = TelloUDPController()

    # 許容外の極端な値
    tello.set_rc(lr=999, fb=-888, ud=150, yaw=-300)
    assert tello._rc_values['lr'] == 100
    assert tello._rc_values['fb'] == -100
    assert tello._rc_values['ud'] == 100
    assert tello._rc_values['yaw'] == -100

    # LineTrace側でのYaw制限
    params = LineTraceParams(yaw_limit=45.0, deadzone=10.0)
    # 極端に右にズレたオフセット
    info = {}
    LineTraceAlgorithm._calc_rc_controls(info, params, is_downward=False, offset_dx=500.0, target_angle=80.0, is_corner=False, corner_dir='none')
    assert abs(info['yaw_value']) <= 45, f"yaw_value {info['yaw_value']} が yaw_limit (45) を超えています"


def test_corner_slowdown_safety():
    """
    安全性テスト 5: 直角コーナーおよび急カーブでの速度抑制
    直角コーナーを検出した際、オーバースピードによるコースアウトを防ぐため
    前進速度が自動的に微速 (fb <= 5) に減速されること。
    """
    params = LineTraceParams(forward_speed=30, yaw_limit=60.0)

    # 直角コーナー判定時
    info = {}
    LineTraceAlgorithm._calc_rc_controls(
        info, params, is_downward=False,
        offset_dx=0.0, target_angle=0.0,
        is_corner=True, corner_dir='right'
    )

    assert info['forward_speed'] <= 5, "直角コーナー検出時に十分減速されていません"
    assert info['yaw_value'] > 0, "右コーナーに対して右旋回が指示されていません"


def test_disconnect_triggers_safety_cleanup():
    """
    安全性テスト 6: 切断時の安全着陸・停止処理
    飛行中(is_flying=True)のまま切断された場合、
    RC制御が停止され、ソケットがクローズされること。
    """
    tello = TelloUDPController()
    tello.is_connected = True
    tello.is_flying = False  # ユニットテストのためソケット送信なしでテスト
    tello.rc_active = True

    tello.disconnect()

    assert tello.is_connected is False
    assert tello.rc_active is False
    assert tello.is_flying is False
    assert tello.sock is None


def test_corrupted_image_crash_resilience():
    """
    安全性テスト 7: 異常画像・極小画像入力時のクラッシュ耐性
    破損フレームや1x1画像、極端なパラメータが与えられても
    プロセスがクラッシュせず安全に未検出(detected=False)で復帰すること。
    """
    engine = LineTraceEngine()
    engine.params.gaussian_ksize = 999  # 巨大なカーネルサイズ

    # 1. None入力
    res1 = engine.process_frame(None)
    assert res1.detected is False

    # 2. 1x1極小画像
    tiny = np.zeros((1, 1, 3), dtype=np.uint8)
    res2 = engine.process_frame(tiny)
    assert res2.detected is False

    # 3. 0要素配列
    empty = np.array([], dtype=np.uint8)
    res3 = engine.process_frame(empty)
    assert res3.detected is False


def test_path_traversal_prevention(client):
    """
    安全性テスト 8: パストラバーサル・不正ファイルアクセス防御
    不適切なファイル名形式やディレクトリトラバーサル試行を400エラーで拒否すること。
    """
    # ディレクトリトラバーサル
    resp = client.get("/api/logs/..%2F..%2Fwindows%2Fsystem32%2Fcmd.exe")
    assert resp.status_code == 400

    # 拡張子違い
    resp2 = client.get("/api/logs/secret.txt")
    assert resp2.status_code == 400


def test_logger_rapid_restarts(tmp_path):
    """
    安全性テスト 9: ロガー連続起動・停止のスレッド安全性
    短時間に start_session / stop_session を連続実行しても
    スレッドデッドロックやファイル競合破損が発生しないこと。
    """
    from src.tello.logger import FlightLogger
    log_dir = str(tmp_path / "rapid_logs")
    fl = FlightLogger(log_dir=log_dir)

    for _ in range(5):
        fl.start_session()
        fl.update_telemetry({'battery': 99})
        fl._record_row()
        fl.stop_session()

    assert len(fl.list_logs()) == 5

