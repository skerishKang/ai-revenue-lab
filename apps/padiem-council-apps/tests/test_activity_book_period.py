from _council_module import run


def test_three_meetings_produce_one_reopenable_activity_book():
    result = run("period_book")
    assert result["selected"] == ["f1", "f2", "f3"]
    assert "3건" in result["status"] and "1건" in result["status"]
    payload = result["payload"]
    assert payload["util"] == "meeting"
    prompt = payload["messages"][0]["content"]
    for expected in ("1월 회의.txt", "3월 회의.txt", "6월 회의.txt", "목차", "월별 활동", "주요 발언", "성과 요약"):
        assert expected in prompt
    assert "7월 회의.txt" not in prompt
    assert "날짜 없는 회의.txt" not in prompt
    assert result["reopened"] == "의정활동집 편집본\n" + result["generated"]
    assert result["endpoints"].count("POST /api/chat/stream") == 1
    assert result["endpoints"].count("POST /api/projects/p1/files") == 1
    assert result["alerts"] == []
    assert result["pageErrors"] == []
