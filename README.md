# BabBell - Slack DM 브로드캐스트 봇

Slack Bolt + Socket Mode를 사용한 식사 알림 DM 브로드캐스트 봇입니다.

## 기능

- **DM 브로드캐스트**: 버튼 클릭으로 구독자에게 일괄 DM 발송
- **Opt-in 구독 모델**: 봇에게 DM을 보내면 자동 구독
- **구독 취소**: "수신 거부" 버튼으로 간편하게 취소
- **오늘의 메뉴**: SNU 식당 메뉴 자동 조회 및 포함 (선택적)
- **쿨다운 & 중복 방지**: 동일 버튼 연속 클릭 방지

## 버튼

| 버튼 | 설명 |
|------|------|
| 지금 밥 | 즉시 출발 알림 + 메뉴 |
| 5분 뒤 밥 | 5분 후 출발 알림 + 메뉴 |
| 취소 | 밥 취소 알림 |
| 간식 | 간식 알림 |
| 수신 거부 | 구독 취소 |

## 요구사항

- Python 3.10+
- [uv](https://github.com/astral-sh/uv) (Python 패키지 관리자)

## 설치 및 실행

### 1. uv 설치

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. 의존성 설치

```bash
# 프로젝트 디렉토리에서
uv sync
```

또는 의존성 직접 추가:

```bash
uv add slack-bolt requests beautifulsoup4
```

### 3. 환경 변수 설정

```bash
cp babbell.env.example babbell.env
# babbell.env 파일을 편집하여 Slack 토큰 입력
```

### 4. 실행

```bash
uv run python main.py
```

## Slack 앱 설정

### 필요한 Bot Token Scopes

- `im:write` - DM 채널 열기 및 메시지 전송
- `conversations:write` - DM 채널 관리
- `users:read` - 사용자 정보 조회 (선택적, 이름 표시용)

### App Token Scopes

- `connections:write` - Socket Mode 연결

### Event Subscriptions

- `message.im` - DM 메시지 수신 (opt-in 처리용)

### Interactivity

- Socket Mode 활성화 필요
- 별도의 Request URL 설정 불필요

## systemd로 배포

### 1. 서비스 파일 설치

```bash
sudo cp babbell.service /etc/systemd/system/
sudo systemctl daemon-reload
```

### 2. 환경 파일 준비

```bash
cp babbell.env.example babbell.env
# babbell.env 편집하여 실제 토큰 입력
```

### 3. 서비스 시작

```bash
sudo systemctl enable babbell
sudo systemctl start babbell
```

### 4. 로그 확인

```bash
sudo journalctl -u babbell -f
```

## 환경 변수

| 변수 | 필수 | 기본값 | 설명 |
|------|------|--------|------|
| `SLACK_BOT_TOKEN` | Yes | - | Slack Bot OAuth Token (xoxb-...) |
| `SLACK_APP_TOKEN` | Yes | - | Slack App-Level Token (xapp-...) |
| `SQLITE_PATH` | No | `./babbell.db` | SQLite DB 파일 경로 |
| `COOLDOWN_SECONDS` | No | `60` | 동일 버튼 쿨다운 (초) |
| `INCLUDE_ACTOR_IN_PUBLIC_MESSAGE` | No | `false` | 브로드캐스트에 클릭자 표시 |
| `ENABLE_TODAYS_MENU` | No | `false` | 오늘의 메뉴 기능 활성화 |
| `MENU_CACHE_TTL_SECONDS` | No | `600` | 메뉴 캐시 TTL (초) |

## 데이터베이스

SQLite를 사용하며, 다음 테이블을 관리합니다:

- `users`: 구독자 정보 (slack_user_id, is_subscribed 등)
- `send_log`: 브로드캐스트 전송 로그

## 프로젝트 구조

```
bab-bell/
├── main.py           # 진입점
├── config.py         # 환경 변수 및 설정
├── db.py             # SQLite 데이터베이스
├── buttons.py        # 버튼 정의
├── menu.py           # 오늘의 메뉴 파싱
├── broadcast.py      # 브로드캐스트 로직
├── handlers.py       # Slack 이벤트/액션 핸들러
├── pyproject.toml    # 프로젝트 설정 (uv)
├── babbell.service   # systemd unit 파일
├── babbell.env.example
└── babbell.yaml.example
```

## 확장

### 버튼 추가

`buttons.py`의 `BUTTON_DEFINITIONS`에 새 버튼 정의를 추가하면 됩니다:

```python
"CAFE": ButtonDefinition(
    value="CAFE",
    label="카페",
    template=":coffee: 밥 봉화대 – 카페로 커피 마시러 가요!",
    is_broadcast=True,
    include_menu=False,
),
```

그리고 `BROADCAST_BUTTON_VALUES` 리스트에 추가:

```python
BROADCAST_BUTTON_VALUES = ["NOW", "IN_5", "CANCEL", "SNACK", "CAFE"]
```

### 웹 집계 페이지 (향후)

`broadcast_id`는 UUID v4로 생성되며, `db.py`의 `create_broadcast_metadata()` 함수를 통해 브로드캐스트 메타데이터가 구조화됩니다. `menu.py`의 `menu_to_dict()` 함수는 메뉴 데이터를 JSON 직렬화 가능한 dict로 변환합니다. 이를 활용하여 웹 기반 집계 페이지를 쉽게 구현할 수 있습니다.
