"""Cross-service clock skew tolerances (#6875 시계 점검 후속).

서로 다른 시계에서 온 시각을 오차 허용 없이 비교하면, 한쪽 시계가 조금만
빨라도 "from the future" 거절이 레인 전체를 막는다. #6869 실측: 승인
워커의 시계가 1초 빠른 것만으로 예약 비교가 전부 거절되어 파일 레인
턴이 503으로 끝났다.

비교하는 두 시계의 출처별로 허용 오차를 여기서만 정하고, 각 비교
지점은 이 이름들을 가져다 쓴다. 이 허용은 "미래 시각" 거절에만
적용하며, 만료(expires_at) 검사와 창 검사는 그대로 둔다.
"""
from __future__ import annotations

from datetime import timedelta

# 서버↔서버(Control Plane→Engine 등): NTP로 운영되는 데이터센터 시계 사이의
# 관측된 흔들림은 초 단위(#6869 실측 ~1초)다. 5초면 그 흔들림을 흡수하면서
# 분 단위 위조 시각은 여전히 거절한다.
SERVER_CLOCK_SKEW_TOLERANCE = timedelta(seconds=5)

# 사용자 PC↔서버(메시 프레즌스·로컬 에이전트 검증): 기기 시계는 정비 상태가
# 제각각이므로 분 단위 앞섬까지 받아들이고, 그보다 큰 분명한 위조만 거절한다.
DEVICE_CLOCK_SKEW_TOLERANCE = timedelta(seconds=300)
