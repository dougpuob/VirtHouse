# QEMU 多實例管理系統 Design Document

**版本**: 1.0  
**日期**: 2026-11-23  
**狀態**: Draft for Prototype Implementation

## 1. 概述

### 1.1 目標
在一台 Ubuntu x86 原生 Linux 主機上，建立一套系統，能夠：

- 大量啟動乾淨、可寫但寫入不持久的 QEMU VM 環境（基於預先做好的 base image）。
- 透過 WebUI 進行管理與操作（含 noVNC 遠端畫面與控制）。
- 提供 RESTful API，讓外部 CI 系統可以索取資源、啟動 VM、查詢就緒狀態、執行測試後釋放資源。
- 支援 PCIe / USB passthrough，並在 WebUI 管理可用裝置。
- 整合 QMP 取得即時 VM 狀態。
- 支援 base image 的製作與管理（含 ISO）。

### 1.2 非目標（Prototype 階段）
- 多使用者權限系統（目前以單人使用為主）。
- 高可用 / 叢集。
- Live migration。

### 1.3 技術選型
- **後端**: Python 3 + FastAPI
- **前端**: 輕量 SPA（建議 Vue 3 或類似）+ noVNC
- **虛擬化**: 直接呼叫 `qemu-system-x86_64`（支援自訂編譯的 binary）
- **磁碟**: qcow2 base + overlay
- **資源限制**: cgroup v2
- **狀態查詢**: QMP (QEMU Machine Protocol)
- **顯示**: QEMU VNC + noVNC (WebSocket)

## 2. 架構總覽

```
┌────────────┐     ┌────────────┐
│   WebUI     │     │   CI System │
│  (Browser)  │     │             │
└──────┬──────┘     └──────┬──────┘
       │ REST / WS         │ REST
       ▼                   ▼
┌───────────────────────────────────┐
│         Backend (FastAPI)        │
│  - VM Lifecycle                  │
│  - Resource Check & Allocation   │
│  - QMP Client                    │
│  - Device Passthrough Manager    │
│  - Image / ISO Manager           │
│  - Config & Template Store       │
└─────────────┬──────────────────┘
               │
       ┌───────┤        ┐
       ▼                ▼
┌────────────┐  ┌────────────┐
│ QEMU Procs  │  │ Host System │
│ + QMP socks │  │ (cgroup,    │
│ + VNC       │  │  vfio, etc) │
└────────────┘  └────────────┘
```

## 3. 儲存與 Image 管理

### 3.1 目錄結構（可在系統 Config 設定）
- `/var/lib/qemu-manager/isos/`：ISO 倉庫
- `/var/lib/qemu-manager/bases/`：正式 Base Image 倉庫（qcow2）
- `/var/lib/qemu-manager/work/`：工作區（製作中的 image、安裝用磁碟）
- `/var/lib/qemu-manager/overlays/`：運行中 VM 的 overlay 檔
- `/var/lib/qemu-manager/qmp/`：QMP socket 檔

### 3.2 Image 生命週期
1. 上傳或放置 ISO 到 ISO 倉庫。
2. 透過 WebUI 建立「安裝用 VM」：選擇 ISO + 設定規格 → 啟動（使用 noVNC 手動安裝）。
3. 安裝完成（含預裝工具、virtio 驅動等）並關機後，可「提升為 Base Image」。
4. Base Image 可供後續測試 VM 使用（每次啟動產生 overlay）。

### 3.3 Picker
WebUI 提供統一 File/Image Picker，可瀏覽、上傳、重新命名、刪除 ISO 與 Base Image，並附帶 metadata（名稱、OS 類型、描述、大小、建立時間）。

## 4. VM 生命週期與磁碟

### 4.1 啟動流程
1. 接收啟動請求（來自 WebUI 或 API）。
2. 檢查資源（CPU、Memory、指定的 passthrough 裝置是否可用）。
3. 不足則回傳明確錯誤（例如 `memory insufficient (need 8192MB, available 4096MB)`）。
4. 產生 overlay qcow2（backing file 指向 base）。
5. 處理 passthrough 裝置（unbind / bind vfio 等）。
6. 啟動 QEMU process（含 QMP socket、VNC）。
7. 套用 cgroup 限制。
8. 進入就緒輪詢。

### 4.2 Overlay 與重置
- 所有寫入進入 overlay。
- 「一鍵重置」：停止 VM → 刪除 overlay → 重新產生 overlay 再啟動（或僅刪除後下次啟動再產生）。
- 關機後預設保留 overlay 直到明確重置或刪除 VM。

## 5. 資源管理與 cgroup

- 啟動前檢查主機可用資源（保留 buffer）。
- 啟動後使用 cgroup v2 限制該 QEMU process 的 memory 與 CPU。
- 定期監控 process 狀態，異常時可通知或自動清理。

## 6. Passthrough 裝置管理

### 6.1 支援類型
- PCIe（透過 vfio-pci）
- USB（透過 usb-host）

### 6.2 管理方式
- Backend 掃描主機裝置（`lspci`、`lsusb`、sysfs）。
- WebUI 裝置管理頁：
  - 列出所有可 passthrough 的裝置。
  - 可啟用/停用「允許被使用」。
  - 可設定顯示名稱與備註。
  - 即時顯示狀態：idle / 被哪個 VM 使用中。
- 只有被標記為允許的裝置，才能在啟動 VM 時選取。
- 分配時機：啟動前（不支援啟動後熱插拔 PCIe 作為主要流程）。

### 6.3 實作要點
- 主機需開啟 IOMMU。
- 啟動前 unbind 原 driver → bind vfio-pci。
- 停止後可選擇是否重新 bind 回原 driver。
- 所有操作需有錯誤處理與回滾。

## 7. 網路

- 每個 VM 使用獨立 subnet（例如 192.168.100.0/24 或可設定）。
- 透過 NAT 讓 guest 可以連到外部。
- IP 可預測（DHCP static 或直接指定）。

## 8. QMP 整合

- 每個 VM 啟動時開啟 QMP unix socket。
- Backend 作為 QMP client：
  - 查詢 `query-status`、CPU、block devices、PCI、USB 等。
  - 監聽事件（SHUTDOWN、GUEST_PANICKED、裝置變化等）。
- 作為「基礎就緒」判斷的重要依據。
- 透過 API 與 WebUI 暴露整理後的資訊。
- 可提供有限制的 QMP command 執行端點（白名單）。

## 9. 就緒輪詢與超時處理

### 9.1 就緒條件（可設定）
1. 基礎就緒：QEMU process 存活 + QMP `query-status` = running + VNC 可連。
2. 系統就緒：SSH port / guest agent / 自訂檢查（可依 Linux / Windows 不同）。
3. 測試就緒：由啟動規格指定。

### 9.2 輪詢
- Backend 背景任務負責輪詢。
- 狀態：`pending` → `starting` → `booting` → `ready` / `failed` / `timeout`。
- 間隔：前期較密，後期較疏。

### 9.3 超時（可設定，以下為建議預設）
- Process 啟動：30s
- 基礎就緒：60s
- 系統就緒：Linux 180s / Windows 300s
- 整體上限：600s

超時後預設：停止 VM、刪除 overlay、釋放裝置、記錄錯誤。可選「失敗時保留」供人工排查（主要給手動操作）。

## 10. Config 與 Template

### 10.1 系統級 Config（必須先設定）
- 路徑設定（ISO、Base、Work 等）
- 資源上限
- 網路設定
- 允許的 base images 註冊資訊
- 全域 timeout 預設值
- QEMU binary 路徑（可覆寫）

### 10.2 VM 啟動規格 / Template
- 名稱
- Base image
- CPU 數量
- Memory
- 要 passthrough 的裝置清單
- Ready check 類型與 timeout
- 其他 QEMU 額外參數
- 可在 WebUI 以表單 + YAML 雙模式編輯、儲存、載入。

## 11. RESTful API（草案）

### VM
- `POST /api/v1/vms`：啟動 VM（body 為啟動規格）
- `GET /api/v1/vms`：列出運行中 VM
- `GET /api/v1/vms/{id}`：詳細資訊
- `GET /api/v1/vms/{id}/status`：狀態（含 ready、error）
- `POST /api/v1/vms/{id}/reset`：一鍵重置
- `DELETE /api/v1/vms/{id}`：停止並清理
- `GET /api/v1/vms/{id}/qmp/...`：QMP 相關查詢

### 資源與裝置
- `GET /api/v1/resources`：目前可用資源
- `GET /api/v1/devices`：裝置清單與狀態
- `PUT /api/v1/devices/{id}`：更新允許狀態 / 名稱

### Image
- `GET /api/v1/images/bases`
- `GET /api/v1/images/isos`
- `POST /api/v1/images/upload`
- `POST /api/v1/images/promote`：將工作中 image 提升為 base

### Config
- `GET/PUT /api/v1/config`
- `GET/POST/PUT/DELETE /api/v1/templates`

所有 API 回傳明確錯誤訊息。

## 12. WebUI 頁面結構

1. **Dashboard**  
   運行中 VM 列表、主機資源概況、快速操作。

2. **VM 管理**  
   啟動新 VM（選 base、規格、裝置、template）、運行中操作（noVNC、重置、停止）、狀態與 QMP 資訊顯示。

3. **裝置管理**  
   掃描結果、啟用/停用、佔用狀態。

4. **Image 管理**  
   ISO / Base / Work 倉庫瀏覽與 Picker、建立安裝用 VM、提升為 Base。

5. **Config / Template**  
   系統設定、Template 編輯器（表單 + YAML）。

noVNC 以 modal 或獨立頁面呈現。

## 13. 實作建議與注意事項

- 使用 `subprocess` + 非同步監控管理 QEMU process。
- QMP 建議使用成熟的 Python library 或自行實作簡單 client。
- Passthrough 操作需 root 或適當權限，建議 Backend 以服務形式運行並做好權限控制。
- 所有關鍵操作（啟動、停止、裝置 bind、檔案刪除）都要有 log。
- Prototype 可先實作核心路徑：啟動 / 停止 / overlay / noVNC / 基本 API，再逐步加入 passthrough、QMP 進階功能、Image 製作流程。
- Windows base image 建議預裝 virtio-win 並考慮 sysprep。
- 需處理 QEMU binary 路徑可設定（支援自訂編譯版本）。

## 14. 後續可擴充項目
- Guest agent 深度整合
- 更精細的網路設定（bridge、固定 MAC 等）
- Snapshot 版本管理
- 更完整的事件通知（Webhook 給 CI）

---

**文件結束**

此文件依據討論內容整理，可供 AI Agent 作為實作 prototype 的依據。實作過程中若遇細節需調整，可再更新此文件。
