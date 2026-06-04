"""
QR Code Reader — QRコード読み取り

OpenCVのQRCodeDetectorを使用。
前処理を強化して検出率を向上させる。
"""

import cv2
import numpy as np
import re
import json
import os
import logging
from typing import Optional, Dict, Tuple, List
from datetime import datetime

logger = logging.getLogger(__name__)


class QRCodeReader:
    """QRコード読み取り＆リンク管理クラス"""

    BASE_URL = "https://motoyucchi.github.io/YYMarkdownSimplePages/#home/"

    def __init__(self, storage_file: str = "qr_links.json"):
        self.storage_file = storage_file
        self.detector = cv2.QRCodeDetector()
        self.stored_links = self._load_links()
        logger.info(f"QRCodeReader 初期化: {len(self.stored_links)} 件保存済み")

    # =========================================================================
    # ストレージ
    # =========================================================================

    def _load_links(self) -> Dict[str, Dict]:
        """保存済みリンクを読み込み"""
        if os.path.exists(self.storage_file):
            try:
                with open(self.storage_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"リンク読み込みエラー: {e}")
        return {}

    def _save_links(self) -> bool:
        """リンクを保存"""
        try:
            with open(self.storage_file, 'w', encoding='utf-8') as f:
                json.dump(self.stored_links, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"リンク保存エラー: {e}")
            return False

    # =========================================================================
    # QRコード検出
    # =========================================================================

    def detect_from_frame(self, frame: np.ndarray) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        フレームからQRコードを検出。
        複数の前処理を試みて検出率を向上。

        Returns:
            (検出成功, QRテキスト)
        """
        # 試行する前処理のリスト
        preprocessors = [
            self._preprocess_adaptive,
            self._preprocess_otsu,
            self._preprocess_sharpen,
            self._preprocess_original,
        ]

        for preprocess in preprocessors:
            try:
                processed = preprocess(frame)
                data, bbox, _ = self.detector.detectAndDecode(processed)
                if data:
                    logger.info(f"QR検出成功: {data}")
                    return True, data
            except Exception as e:
                logger.debug(f"前処理 {preprocess.__name__} でエラー: {e}")
                continue

        return False, None

    def _preprocess_adaptive(self, frame: np.ndarray) -> np.ndarray:
        """適応的閾値処理"""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        return cv2.adaptiveThreshold(
            blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 11, 2
        )

    def _preprocess_otsu(self, frame: np.ndarray) -> np.ndarray:
        """大津の閾値処理"""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        _, thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return thresh

    def _preprocess_sharpen(self, frame: np.ndarray) -> np.ndarray:
        """シャープニング"""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        kernel = np.array([[-1, -1, -1],
                           [-1,  9, -1],
                           [-1, -1, -1]])
        return cv2.filter2D(gray, -1, kernel)

    def _preprocess_original(self, frame: np.ndarray) -> np.ndarray:
        """前処理なし（元フレームのまま）"""
        return frame

    # =========================================================================
    # ユーティリティ
    # =========================================================================

    # _extract_three_digit and generate_link removed as we now support arbitrary text

    # =========================================================================
    # リンク管理
    # =========================================================================

    def process_detection(self, frame: np.ndarray) -> Dict:
        """QRコード検出の完全処理"""
        result = {
            'success': False,
            'qr_detected': False,
            'qr_text': None,
            'already_stored': False,
            'newly_stored': False,
            'message': '',
        }

        detected, qr_text = self.detect_from_frame(frame)

        if not detected:
            result['message'] = 'QRコードが検出されませんでした'
            return result

        result['qr_detected'] = True
        result['qr_text'] = qr_text

        # Using the qr_text as the key
        if qr_text in self.stored_links:
            result['already_stored'] = True
            result['message'] = f'テキストは既に保存されています'
        else:
            self.stored_links[qr_text] = {
                'link': qr_text if qr_text.startswith("http") else None,
                'qr_text': qr_text,
                'timestamp': datetime.now().isoformat(),
            }
            if self._save_links():
                result['newly_stored'] = True
                result['message'] = f'新しいテキストを保存しました'
            else:
                result['message'] = 'テキストの保存に失敗しました'
                return result

        result['success'] = True
        return result

    def get_stored_links(self) -> Dict[str, Dict]:
        """保存済みリンク一覧"""
        return self.stored_links.copy()

    def delete_link(self, three_digit: str) -> bool:
        """リンク削除"""
        if three_digit in self.stored_links:
            del self.stored_links[three_digit]
            return self._save_links()
        return False

    def clear_links(self) -> bool:
        """全リンク削除"""
        self.stored_links.clear()
        return self._save_links()

    def get_stats(self) -> Dict:
        """統計情報"""
        return {
            'total_stored': len(self.stored_links),
            'storage_file': self.storage_file,
            'latest_numbers': list(self.stored_links.keys())[-5:],
        }
