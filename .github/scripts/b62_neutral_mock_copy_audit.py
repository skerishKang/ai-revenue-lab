from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# R5 0단계(0-2): app.js에서 chat-*-module.js로 옮겨진 문구도 같은 감사 대상이다.
# 새 모듈(chat-*-module.js)은 index.html에 script 줄만 추가되면 여기에 자동으로 들어온다.
STATIC = ROOT / "apps/padiem-chat/static"
TARGETS = [
    ROOT / "apps/padiem-chat/app/b14_client.py",
    STATIC / "app.js",
    STATIC / "chat-app-context.js",
    *sorted(STATIC.glob("chat-*-module.js")),
]
FORBIDDEN = (
    "승인된 기본 모델 경로",
    "어떤 AI를 쓸지는 파디엠이 자동으로 고릅니다.",
    "현재 모델 선택",
)


def main() -> None:
    hits = []
    for path in TARGETS:
        text = path.read_text(encoding="utf-8")
        for phrase in FORBIDDEN:
            if phrase in text:
                hits.append(f"{path.relative_to(ROOT)}: {phrase}")
    if hits:
        raise SystemExit("stale B62 model-selection copy found:\n" + "\n".join(hits))
    print("B62 neutral mock/product copy audit: PASS")


if __name__ == "__main__":
    main()
