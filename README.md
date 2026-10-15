# Tello Drone Web Controller

WiFiバインド対応・LineTrace（LSD線分検出）搭載 Telloドローン制御Webアプリケーション  
*A web-based DJI Tello drone controller with explicit WiFi interface binding, LineTrace (LSD line segment detection), and late-2010s dark-mode UI.*

---

## 主な特徴 / Features

- **生UDPソケットによる明示的WiFiバインド**: 有線LANとWiFiが共存するPCでもTelloと通信しやすい設計
- **実用的なLineTraceアルゴリズム (OpenCV LSD)**: 直線・曲線・直角コーナー追従、通常機体（前方微下向き）と改造機体（ほぼ真下向き）の双方に対応
- **ロスト時復帰支援 & コーナー設定**: コーナー旋回速度の手動設定 (1〜100)、コーナー方向保持（最大20秒）、直前位置への後退復帰（バックトラック）、ホバリング時360°自動旋回探索
- **低遅延映像ストリーミング & 遅延調整**: キャプチャと画像処理の分離、滞留フレームの手動フラッシュ対応
- **2010年代後半調のダークテーマ**: ギラつきのない落ち着いたダークグレーUI、高可読性
- **PC & スマホ両対応の操作系**: PCキーボード操作 ＋ スマホ用オンスクリーン・タッチパッド（D-Pad）
- **HTTP環境（非Secure Context）に配慮した設計**: スマホ接続時のWeb API制約下でも安全に動作
- **飛行ログ (Timeline CSV) & 静止画撮影 (PNG)**: フライトデータCSV保存（標準1Hz / 試験的機能時10Hz）と最新フレームPNGダウンロード
- **四角コース周回計測（試験的機能）**: 4直角コーナー判定による周回数（Lap）およびラップタイムの自動集計・HUD表示

---

## クイックスタート / Quick Start

### Windows
```bat
start.bat
```

### macOS / Linux
```bash
chmod +x start.sh
./start.sh
```

ブラウザで `http://localhost:8000` を開きます。  
スマートフォンから操作する場合は、同一Wi-Fiに接続した上で `http://<PCのIPアドレス>:8000` を開きます。

---

## ドキュメント / Documentation

詳細なセットアップ手順、操作方法、API仕様、トラブルシューティング、および安全上の注意は各ドキュメントをご参照ください。

- [日本語ドキュメント (Japanese Documentation)](docs/README.md)
- [English Documentation](docs/README_EN.md)

---

## ライセンス / License

MIT License
