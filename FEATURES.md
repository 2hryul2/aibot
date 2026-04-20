# Ditoo Pro 통합 제어 시스템

Divoom Ditoo Pro(16x16 LED 디스플레이)를 Windows 알림 시스템과 연동한 통합 제어 프로젝트.

## 구성 요약

| 영역 | 설명 |
|------|------|
| **디바이스 제어** | 블루투스 RFCOMM 기반 Ditoo Pro 직접 제어 |
| **Claude Code 연동** | 생각 중/응답 완료 시 아이콘 + 키보드 LED 효과 |
| **알림 감시** | Windows 프로그램 알림을 감지하여 디바이스에 표시 |
| **트레이 앱** | 시스템 트레이 아이콘으로 백그라운드 실행 |
| **설정 GUI** | 감시할 프로그램을 화면에서 선택·관리 |

---

## 1. 디바이스 제어 (`ditoo_connection.py`)

### 지원 기능
- 블루투스 연결 (MAC: `B1:21:81:24:1D:1E`, RFCOMM port 2)
- 텍스트 스크롤 표시 (폰트 커스터마이징 가능)
- 아이콘/이미지 표시 (PNG/GIF/JPG/BMP → 자동 16x16 변환)
- 시계 표시
- 밝기 조절 (0~100)
- **키보드 LED 제어** (on/off, 다음/이전 효과)

### 주요 CLI 스크립트
```bash
python ditoo_send.py "텍스트"                    # 스크롤 텍스트
python ditoo_clock.py                          # 시계
python ditoo_image.py "경로.png"                 # 이미지
python ditoo_thinking.py  (stdin에 '{}' 전달)     # Claude 아이콘
```

---

## 2. Claude Code 연동

| 상태 | 디스플레이 | 키보드 LED |
|------|----------|-----------|
| **사용자 입력** (thinking) | `claude_thinking` 아이콘 | 켜기 → 초록색 회전 |
| **응답 완료** (done) | `claude_done` 아이콘 | 끄기 |
| **5초 후** | 시계 복귀 | - |
| **30분 timeout** | 시계 복귀 | - |

훅 파일: `ditoo_hook.py` (UserPromptSubmit / Stop)

---

## 3. 이미지 변환 엔진

### `image_to_divoom16()`
- 입력: PNG/GIF/JPG/BMP
- 처리: 16x16 NEAREST 리사이즈 → 팔레트 추출(최대 255색) → bit-packed 인코딩
- 출력: `.divoom16` 바이너리 (프레임당 magic byte `0xAA` + 길이 + 시간 + 팔레트 + 픽셀)
- GIF 멀티프레임 자동 처리

### divoom16 프로토콜
```
[프레임]
0xAA | 길이(2LE) | 시간(2LE) | 팔레트재사용(1) | 색상수(1) | 팔레트(RGB) | 픽셀(비트패킹)
```

---

## 4. 알림 감시 시스템 (`notification_watcher.py`)

### 감지 방식 3가지

| 방식 | 용도 | 예시 |
|------|------|------|
| `shadow_wnd` | 특정 윈도우 클래스 CREATE 감지 | 카카오톡 (`KakaoTalkShadowWndClass`) |
| `toast_db` | Windows 알림 DB(wpndatabase.db) 폴링 | Claude Desktop (HandlerId 기반) |
| `window_create` | 프로세스의 새 윈도우 생성 감지 (범용) | 임의 프로그램 |

### 공통 동작 흐름
```
알림 감지
  ├─ 디바이스에 이미지 표시
  ├─ 키보드 LED 효과 적용 (선택)
  ├─ 사용자가 해당 앱을 열 때까지 반복 표시
  └─ 확인 후 → 시계 복귀 + LED 끄기
```

### 오탐 방지
- **PID 스코핑**: 대상 프로세스의 이벤트만 후킹
- **포그라운드 체크**: 사용자가 이미 보고 있으면 무시
- **쿨다운**: 연속 알림 중복 처리 방지

---

## 5. 시스템 트레이 앱

### 트레이 메뉴
```
● Running / Stopped           (상태 표시)
─────────────────
Start                         (감시 시작)
Stop                          (감시 중지)
─────────────────
Watchers ▶                    (등록된 감시 목록)
Config...                     (설정 GUI 열기)
Reload                        (설정 재적용)
─────────────────
Quit
```

### 자동 실행
- `pythonw.exe`로 실행되어 콘솔 창 없음
- 시작프로그램 등록: `python notification_watcher.py --install`
- 해제: `python notification_watcher.py --uninstall`

---

## 6. 설정 GUI (`config_gui.py`)

### 기능
- **등록된 Watcher 목록**: 체크박스로 ON/OFF, X 버튼으로 삭제
- **실행 중인 프로그램 목록**: 현재 작업표시줄의 프로그램 표시 (exe + 타이틀)
- **프로그램 선택 → 자동 등록**: `window_create` 방식으로 저장
- **저장 & Reload**: config.json 갱신 후 감시 재시작

### Watcher 설정 구조 (`config.json`)
```json
{
  "watchers": [
    {
      "name": "KakaoTalk",
      "enabled": true,
      "detect_method": "shadow_wnd",
      "window_title": "카카오톡",
      "shadow_class": "KakaoTalkShadowWndClass",
      "window_class": "EVA_Window_Dblclk",
      "image": "kakao.bmp",
      "keyboard_effect": 2,
      "cooldown": 10,
      "repeat_interval": 10
    }
  ]
}
```

---

## 7. 현재 등록된 감시 대상

| 프로그램 | 감지 방식 | 이미지 | 키보드 효과 |
|---------|----------|--------|------------|
| **KakaoTalk** | shadow_wnd | kakao.bmp | 노란색 스누즈 |
| **Claude Desktop** | toast_db | claude.bmp | - |
| **Antigravity** | window_create | default_notify.bmp | - |

---

## 파일 구조

```
claude-ditoo/
├── ditoo_connection.py       # 디바이스 제어 코어
├── ditoo_send.py             # 텍스트 + 응답 완료 훅
├── ditoo_thinking.py         # 생각 중 훅
├── ditoo_hook.py             # Claude Code 훅 연결
├── ditoo_clock.py            # 시계 표시
├── ditoo_image.py            # 이미지 CLI
├── ditoo_watchdog.py         # 30분 timeout 감시
├── notification_watcher.py   # 트레이 앱 + 알림 감시
├── config_gui.py             # 설정 GUI
├── config.json               # 전체 설정
├── claude_thinking.png/.divoom16
├── claude_done.divoom16
├── claude_icon.png/.divoom16
├── kakao.bmp
├── default_notify.bmp
└── FEATURES.md               # 이 문서
```

---

## 슬래시 명령어 (`/ditoo`)

```
/ditoo 시계
/ditoo 텍스트 안녕하세요
/ditoo 아이콘
/ditoo 이미지 경로/파일.png
/ditoo 밝기 80
```
