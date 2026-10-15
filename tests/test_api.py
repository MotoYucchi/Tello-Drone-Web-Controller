"""
FastAPI エンドポイント結合テスト
"""

import pytest
import numpy as np
from fastapi.testclient import TestClient
from src.server.app import app, app_state


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


def test_status(client):
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert "tello" in data
    assert "linetrace" in data
    assert "camera_mode" in data["linetrace"]


def test_linetrace_params(client):
    # パラメータ設定テスト
    new_params = {
        "camera_mode": "downward",
        "h_min": 10,
        "h_max": 30,
        "s_min": 100,
        "s_max": 255,
        "v_min": 100,
        "v_max": 255,
        "gaussian_ksize": 7,
        "forward_speed": 20,
        "deadzone": 15.0,
        "yaw_limit": 50.0,
        "corner_recovery_back_speed": 48,
        "corner_memory_sec": 15.0,
        "lost_auto_rotate": True,
        "lost_backtrack": True,
    }
    response = client.post("/api/linetrace/params", json=new_params)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["params"]["camera_mode"] == "downward"
    assert data["params"]["forward_speed"] == 20
    assert data["params"]["gaussian_ksize"] == 7
    assert data["params"]["corner_recovery_back_speed"] == 48
    assert data["params"]["corner_memory_sec"] == 15.0
    assert data["params"]["lost_auto_rotate"] is True
    assert data["params"]["lost_backtrack"] is True


def test_screenshot_when_not_streaming(client):
    """映像未開始時のスクリーンショット取得（400エラー想定）"""
    response = client.get("/api/screenshot")
    assert response.status_code == 400


def test_screenshot_when_streaming(client):
    """映像フレームが存在する場合のスクリーンショット(PNG)取得"""
    video = app_state.get('video')
    if video:
        video.streaming = True
        dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        with video._frame_lock:
            video._current_frame = dummy_frame

        response = client.get("/api/screenshot")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert "Content-Disposition" in response.headers
        assert "TELLO_" in response.headers["Content-Disposition"]
        assert ".png" in response.headers["Content-Disposition"]

        video.streaming = False


def test_flight_logs_api(client):
    """フライトログ一覧・ダウンロードテスト"""
    logger = app_state.get('logger')
    if logger:
        # セッション開始して1行記録
        logger.start_session()
        logger.update_telemetry({'battery': 90, 'flight_time': 5})
        logger._record_row()
        logger.stop_session()

    response = client.get("/api/logs")
    assert response.status_code == 200
    logs = response.json().get("logs", [])
    assert len(logs) > 0

    # 最新ログダウンロード
    dl_resp = client.get("/api/logs/latest")
    assert dl_resp.status_code == 200
    assert dl_resp.headers["content-type"] == "text/csv; charset=utf-8"


def test_video_latency_and_buffer_reset_api(client):
    """映像遅延設定およびバッファリセットAPIのテスト"""
    # 1. 遅延パラメータ設定
    resp_lat = client.post("/api/video/latency", json={"low_latency": True, "drain_rate": 2})
    assert resp_lat.status_code == 200
    assert resp_lat.json()["success"] is True
    assert resp_lat.json()["stats"]["drain_rate"] == 2

    # 2. バッファリセット (未ストリーミング時は安全メッセージ返却)
    resp_reset = client.post("/api/video/reset_buffer")
    assert resp_reset.status_code == 200


def test_experimental_and_course_api(client):
    """試験的機能とコース周回設定APIのテスト"""
    # 1. 試験的機能の初期状態
    status_resp = client.get("/api/experimental/status")
    assert status_resp.status_code == 200

    # 2. 有効化
    enable_resp = client.post("/api/experimental/enable")
    assert enable_resp.status_code == 200
    assert enable_resp.json()["experimental_features"] is True

    # 3. コース設定 (四角コース)
    course_resp = client.post("/api/linetrace/course", json={"course_type": "square"})
    assert course_resp.status_code == 200
    assert course_resp.json()["course_type"] == "square"

    # 4. 周回数リセット
    reset_resp = client.post("/api/linetrace/reset_laps")
    assert reset_resp.status_code == 200
    assert reset_resp.json()["success"] is True

    # 5. 無効化 (クリーンリセット)
    disable_resp = client.post("/api/experimental/disable")
    assert disable_resp.status_code == 200
    assert disable_resp.json()["experimental_features"] is False

