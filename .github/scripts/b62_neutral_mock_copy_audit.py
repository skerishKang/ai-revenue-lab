from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGETS = [
    ROOT / "apps/padiem-chat/app/b14_client.py",
    ROOT / "apps/padiem-chat/static/app.js",
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
