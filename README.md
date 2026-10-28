<!-- hannun-meal-directory-publisher v1 -->
# 한눈급식 전국 학교 목록

공식 NEIS 학교기본정보에서 공개 초·중·고 학교 목록만 생성해 Pages로 배포합니다. Android 앱 소스, Worker 소스, APK, 서명키는 이 저장소에 포함하지 않습니다.

NEIS_API_KEY는 Actions Secret으로만 설정합니다. DIRECTORY_READY=true 설정 후 주간/수동 workflow를 실행합니다. 생성 실패 시 기존 배포를 유지합니다. 초기 인증키 준비 전에는 배포하지 않으며 예시 학교 데이터를 게시하지 않습니다.
