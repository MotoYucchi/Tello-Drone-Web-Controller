"""
FlightLogger 単体テスト
"""

import os
import csv
import time
import pytest
from src.tello.logger import FlightLogger


def test_logger_lifecycle(tmp_path):
    """ロガーのライフサイクルとCSV出力テスト"""
    log_dir = str(tmp_path / "test_logs")
    logger = FlightLogger(log_dir=log_dir)

    filepath = logger.start_session()
    assert filepath is not None
    assert os.path.exists(filepath)
    assert logger.is_logging is True

    # データ更新
    logger.update_telemetry({
        'battery': 85,
        'height': 50,
        'flight_time': 12,
        'pitch': 1,
        'roll': 0,
        'yaw': 10,
    })
    logger.update_rc(0, 20, 0, 15, mode="linetrace")
    logger.update_linetrace({
        'detected': True,
        'center_x': 250,
        'center_y': 200,
        'offset_dx': 10.0,
        'angle_deg': 5.0,
        'is_corner': False,
    })
    logger.log_event("Test takeoff")

    # 1行手動書き込みテスト
    logger._record_row()

    # ログ停止
    last_file = logger.stop_session()
    assert last_file == filepath
    assert logger.is_logging is False

    # CSVの中身検証
    with open(filepath, mode='r', encoding='utf-8-sig') as f:
        reader = list(csv.reader(f))
        assert len(reader) >= 2  # ヘッダー + 1行以上
        headers = reader[0]
        assert "timestamp" in headers
        assert "battery_pct" in headers
        assert "control_mode" in headers

        data_row = reader[-1]
        battery_idx = headers.index("battery_pct")
        assert data_row[battery_idx] == "85"
        mode_idx = headers.index("control_mode")
        assert data_row[mode_idx] == "linetrace"
        event_idx = headers.index("event_note")
        assert "Test takeoff" in data_row[event_idx]


def test_list_logs(tmp_path):
    """ログファイル一覧取得のテスト"""
    log_dir = str(tmp_path / "test_logs")
    logger = FlightLogger(log_dir=log_dir)

    assert len(logger.list_logs()) == 0

    f1 = logger.start_session()
    logger.stop_session()

    logs = logger.list_logs()
    assert len(logs) == 1
    assert logs[0]["filename"] == os.path.basename(f1)
