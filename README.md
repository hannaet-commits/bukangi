# 부캉이 (Bukangi) 🦈

## ⬇️ 바로 받아서 쓰기 (Windows)

**[Bukangi.exe 내려받기](https://github.com/hannaet-commits/bukangi/releases/latest/download/Bukangi.exe)** — 더블클릭하면 바로 실행됩니다 (파이썬 설치 필요 없음).
종료는 상어 우클릭 메뉴 또는 트레이 아이콘에서 합니다.

> 처음 실행할 때 "Windows의 PC 보호" 파란 창이 뜨면 **추가 정보 → 실행** 을 누르세요. (개인이 만든 프로그램이라 서명이 없어서 나오는 안내입니다)

Windows 바탕화면을 자유롭게 헤엄치는 흑상어 데스크톱 펫. Python 3.11+ / PySide6.

## 빠른 시작 (가상환경)

```powershell
# 1) 가상환경 만들기 + 설치 (처음 한 번)
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2) 실행
.venv\Scripts\python.exe main.py
```

더블클릭으로 쓰려면: `setup_venv.bat`(최초 1회) → `run.bat`

| 명령 | 설명 |
| --- | --- |
| `run.bat` | 일반 실행 (콘솔 창 없음) |
| `run_test.bat` | 테스트 모드 (콘솔 로그 + 우클릭 메뉴에 `[테스트] 애니메이션`) |
| `.venv\Scripts\python.exe main.py --check` | PNG 에셋 18장 검사만 하고 종료 |
| `.venv\Scripts\python.exe main.py --placeholder` | PNG 대신 임시 상어로 실행 |
| `.venv\Scripts\python.exe main.py --test --turn loop` | 방향 전환(turn)을 계속 반복 (`r2l`/`l2r` 은 한 번만) |
| `.venv\Scripts\python.exe main.py --test --state swim --direction left` | 시작 상태/방향 지정 |
| `.venv\Scripts\python.exe -m unittest discover tests -v` | 단위 테스트 |
| `.venv\Scripts\python.exe tests\smoke_run.py` | 실제 화면 스모크 테스트 (스크린샷은 `.tmp/`) |
| `.venv\Scripts\python.exe tools\preview_swim.py` | 유영 미리보기 창 (재생 방식/주기 바꿔 보기) |
| `.venv\Scripts\python.exe tools\preview_swim.py --report` | 프레임 간 차이 표 + 어색한 구간 점검 |
| `.venv\Scripts\python.exe tools\preview_swim.py --gif --turn` | `.tmp/preview/` 에 GIF 저장 (PNG 원본은 수정 안 함) |

(`tools\` 는 `pip install -r requirements-dev.txt` 로 Pillow/numpy 가 있어야 합니다.)

## 조작법

- **드래그**: 왼쪽 버튼으로 끌어서 이동 (놓은 위치가 화면 밖이면 화면 안으로 복귀)
- **더블클릭**: 말풍선 ("부캉!", "헤엄치는 중…" …)
- **우클릭 메뉴**: 일시정지/다시 움직이기, 속도(느리게·보통·빠르게), 크기(작게·보통·크게), 항상 위, 종료
- **투명한 부분 클릭**: 상어 모양 바깥은 클릭이 뒤의 창으로 통과
- 시스템 트레이 아이콘: 보이기/숨기기, 말하기, 종료

## 동작 방식

- **상태 4개**: `swimming_right`, `swimming_left`, `turning_right_to_left`, `turning_left_to_right`
- 화면 끝에 가까워지면 서서히 느려지고(`TURN_SLOW_ZONE`), 끝에서 80~120px 안으로 들어오면 turn 을 시작합니다.
- turn 중에는 turn_01 → turn_08 만 재생하고(헤엄 프레임 없음) 거의 제자리에서 돕니다. 끝나면 반대 방향으로 천천히 다시 헤엄칩니다.
- 왼쪽으로 헤엄 = `swim_right` 좌우 반전, 왼쪽→오른쪽 turn = `turn_right_to_left` 좌우 반전.
- 꼬리(기본, `SWIM_PROCEDURAL = True`): `swim_right/frame_01.png` **한 장만** 기준으로 쓰고, 몸 뒤쪽을 코드로 사인파처럼 휘게 한
  16프레임을 만들어 재생합니다. 머리/몸/지느러미는 안 움직여서 프레임 교체로 인한 깜빡임·크기 변화가 없습니다.
  (예전 방식: 10장을 `SWIM_SMOOTH_PATH` 순서로 섞어 재생 → `SWIM_PROCEDURAL = False`)
  한 주기는 속도 프리셋마다 느리게 4초 / 보통 3초 / 빠르게 2초이고, 화면 이동 속도와는 별개입니다.

## 프로젝트 구조

| 파일 | 역할 |
| --- | --- |
| `main.py` | 진입점. 인자 처리, 로그, 중복 실행 방지, 트레이 아이콘 |
| `settings.py` | 크기/속도/타이머/문구/재생 순서/프레임 위치 보정 등 **모든 숫자 설정**, 에셋 경로(`resource_path`), 사용자 설정 저장 |
| `asset_check.py` | PNG 18장 검사(존재/PNG 여부/손상/알파/크기·비율) |
| `animation.py` | 스프라이트 로딩 → 위치 보정 → 공통 영역 크롭 → 크기별 렌더 캐시, 꼬리 타임라인(`SwimTimeline`), 프레임 재생(`AnimationPlayer`) |
| `placeholder.py` | 에셋이 없을 때 코드로 그리는 임시 상어 |
| `behavior.py` | 이동/상태(`PetState`) 로직. 화면과 무관한 순수 로직 |
| `pet_window.py` | 투명 창, 드래그, 우클릭 메뉴, 타이머 루프, 테스트 모드 |
| `speech_bubble.py` | 말풍선 창 |
| `tests/` | `test_core.py`(단위), `smoke_run.py`(실제 화면), `bench_cpu.py`(CPU 측정) |
| `tools/` | `analyze_frames.py`(프레임 분석), `preview_swim.py`(미리보기/GIF) |
| `.cursor/rules/` | Cursor 규칙 |

## 에셋

```text
assets/
├── swim_right/          frame_01.png ~ frame_10.png   (오른쪽을 보는 헤엄 10프레임)
├── turn_right_to_left/  turn_01.png ~ turn_08.png     (오른쪽→왼쪽 방향 전환 8프레임)
├── idle/ blink/ swim_rigth_old/                       (예전 에셋. 지금은 사용 안 함, 삭제하지 않음)
```

- **같은 파일 이름**으로 PNG를 덮어쓰면 됩니다. 모든 이미지는 **같은 캔버스 크기**, 투명 배경(알파)으로 맞춰 주세요.
- 상어는 **오른쪽**을 보게 그립니다. 왼쪽은 코드에서 자동 반전합니다.
- 파일 이름에 번호가 있으면 `frame_02` → `frame_10` 순으로 숫자 기준 정렬합니다.
- 파일이 없거나 손상되면 정확히 어떤 파일인지 안내합니다. 헤엄 이미지가 없으면 임시 상어로, turn 이미지만 없으면 방향 전환 없이(끝에서 바로 반전) 실행합니다.
- 프레임마다 그림 위치가 조금씩 달라서, `settings.py` 의 `SWIM_FRAME_OFFSETS`, `TURN_FRAME_OFFSETS` 로 **메모리상에서만** 위치를 맞춰 씁니다 (PNG 원본은 그대로).
- 눈 깜빡임은 새 PNG 에 감은 눈 그림이 없어서, 눈 위에 눈꺼풀을 코드로 덮어 그립니다 (`BLINK_*`).

## 테스트 모드

`run_test.bat` 또는 `main.py --test` 로 실행하면 우클릭 메뉴에 `[테스트] 애니메이션`이 생깁니다.

- 자동(기본) / 헤엄 고정 / 가만히 고정 / 눈 깜빡임 고정
- ▶ 오른쪽→왼쪽 턴 실행 / ◀ 왼쪽→오른쪽 턴 실행 / 턴 계속 반복
- ← 왼쪽으로 헤엄 (턴 없이) / → 오른쪽으로 헤엄 (턴 없이)
- 현재 상태 보기 (말풍선에 `상태 | 프레임 | 속도 | 꼬리 위상` 표시)

## exe 만들기 (PyInstaller)

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --noconsole --name Bukangi --add-data "assets;assets" main.py
```

(또는 `build_exe.bat`) 결과: `dist\Bukangi.exe`

- 에셋은 exe 안에 포함됩니다. exe **옆에 `assets` 폴더를 두면 그쪽이 우선**이라 다시 빌드하지 않고도 이미지를 바꿀 수 있습니다.
- 로그: `%LOCALAPPDATA%\Bukangi\bukangi.log`

## 설정 팁 (`settings.py`)

| 하고 싶은 것 | 바꿀 값 |
| --- | --- |
| 꼬리 한 주기(초) | `SPEED_PRESETS` 의 `tail_period` (느리게 4 / 보통 3 / 빠르게 2) |
| 화면 이동 속도 | `SPEED_PRESETS` 의 `pixels_per_sec` |
| 꼬리 좌우 흔들림 폭 (바깥으로 / 안쪽으로) | `TAIL_SWAY_OUT`(기본 0.06, 원본보다 더 길게 펴지는 폭), `TAIL_SWAY_IN`(기본 0.02, 오므리는 폭) — 몸 길이 대비 |
| 꼬리 위아래 휘는 폭 (기본 0 = 위아래로 안 움) / 모양 | `TAIL_WAVE_AMPLITUDE`(폭), `TAIL_WAVE_REGION`(휘는 범위), `TAIL_WAVE_POWER`, `TAIL_WAVE_LAG`(꼬리 끝 지연) |
| 꼬리 기준 그림 바꾸기 | `SWIM_BASE_FRAME` (파일 번호) |
| 꼬리 프레임 순서 (`SWIM_PROCEDURAL = False` 일 때) | `SWIM_SMOOTH_PATH` (파일 번호, 1부터). `SWIM_ORDER_MODE` 를 `"file"`/`"pingpong"` 으로 바꾸면 단순 재생 |
| 끝에서 천천히 도는 정도 | `SWIM_EASE_STRENGTH`, `SWIM_SEGMENT_WEIGHTS` (구간별 시간 가중치) |
| 프레임 섞기 끄기 | `SWIM_CROSSFADE = False` |
| turn 시간/속도 | `TURN_DURATION`, `TURN_DRIFT_FACTOR` |
| turn 시작 위치 | `TURN_TRIGGER_RANGE`(끝에서 px), `TURN_SLOW_ZONE`, `TURN_MIN_SPEED_FACTOR` |
| turn 때 몸집이 커졌다 작아지는 정도 | `TURN_NORMALIZE_SIZE`(켬/끔), `TURN_SIZE_STRENGTH`(1.0=완전히 같은 크기) |
| 방향 전환 방식 (`"art"` turn PNG 재생(기본) / `"flip"` 납작하게 눌러 뒤집기) | `TURN_STYLE`, `TURN_FLIP_DURATION`, `TURN_FLIP_MIN_SCALE` |
| 꼬리가 화면 쪽으로 오가는 느낌(크기 변화) | `TAIL_DEPTH_SCALE` (0 이면 끔) |
| (art 방식) turn 중 몸 위치(높이 고정, 가로는 부드럽게 이동) | `TURN_AUTO_ALIGN`, `TURN_ALIGN_EASE` |
| turn 이 끝난 뒤 꼬리 자세 자동 맞춤 | `TURN_AUTO_EXIT_FRAME` |
| 둥실거림 폭이 바뀔 때 걸리는 시간 | `BOB_AMP_SMOOTHING` (초) |
| turn 프레임이 어긋날 때 | `TURN_FRAME_OFFSETS`, `TURN_EXIT_SWIM_FRAME`, `TURN_CROSSFADE_SEGMENTS` |
| 더 부드럽게 / CPU 절약 | `TICK_MS` (16 / 33), `animation.BLEND_STEPS` |
| 멈추는 빈도 | `SWIM_DURATION_RANGE`, `IDLE_DURATION_RANGE` |
| 깜빡임 | `BLINK_ENABLED`, `BLINK_INTERVAL_RANGE`, `BLINK_MIN_GAP`, `EYE_POS_SRC` |
| 말풍선 문구 | `SPEECH_LINES` |
| 크기 | `SIZE_PRESETS` |

## 알려진 한계 / 다음 개선 아이디어

- 새 `swim_right` 10장은 프레임마다 몸 길이/모양/명암이 달라서 섞어 재생하면 깜빡이고 크기가 변해 보였습니다.
  그래서 지금은 한 장을 기준으로 꼬리를 코드로 휘게 합니다. 꼬리는 "위아래로 휘는 막대"에 가깝게 움직이고(지느러미 모양까지 바뀌지는 않음),
  더 자연스럽게 하려면 꼬리를 좌/우 최대로 휘게 한 프레임과 그 사이 중간 프레임(같은 스타일·같은 몸통 위치)이 필요합니다.
- frame_02(스타일/모양이 다름)와 frame_09(위치/모양 차이가 큼)는 이상치입니다. 꼬리 파도 모드에서는 쓰지 않습니다.
- turn 프레임은 머리/몸통 위치가 프레임마다 그림 안에서 크게 움직입니다(특히 turn_04). 코드에서 위치만 맞췄고 모양 자체는 고치지 않았습니다.
- 새 PNG 에는 눈 감김/idle 그림이 없어서 눈 깜빡임은 코드로 덮어 그립니다. 가까이서 보면 그림 느낌과 약간 다릅니다.
- 아이디어: 마우스 커서 따라가기/피하기, 시간대별 대사, 먹이 클릭, 작업표시줄 위를 걷는 모드, 멀티 모니터 건너가기.
