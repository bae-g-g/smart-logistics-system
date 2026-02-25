#!/bin/sh

'''


tailscale이 컨테이너로 동작하면, 라우팅 테이블을 가상 ip로 덮어쓰기 때문에
로컬에서 연결되어야 하는  엣지 디바이스간 통신은 실제 라즈베리파이의 lan으로 나가야한다.
그렇기 때문에 실제 lan으로 나가는 트래픽과 가상ip로 나가는 트래픽을 분리해야한다.
라우팅 테이블은 가상ip로 모두 통신하기 때문에 lan으로 나가는 출구 ip를 찾아야함


'''
 

set -e # 에러시 멈춤 안전장치

echo "[routing.sh] 라우팅 테이블 설정 시작..."

# Tailscale 데몬 시작 (가상 인터페이스 tailscale0 생성 보장) 
echo "Tailscale 1/3 시작..."



tailscaled --statedir=/var/lib/tailscale & # 백그라운드에서 테일스케일 실행
TAILSCALED_PID=$!

#테일스케일 데몬(가상 랜카드 세팅)이 완전히 올라올 때까지 잠시 대기
sleep 3

#  Tailscale 로그인 및 네트워크 합류 
echo "Tailscale 2/3 인증 중..."



tailscale up \  
    --authkey="${TS_AUTHKEY}" \ 
    --hostname="${TS_HOSTNAME:-rpi-factory}" \
    --netfilter-mode=off

# --authkey : 테일스케일 인증키 (https://login.tailscale.com/admin/machines/new/authkey)
# --hostname: 테일스케일 호스트네임
# 도커-컴포즈.yml 에서 각 변수는 .env에서 가져오도록 설정함

echo "Tailscale 3/3 연결 완료"


#  Docker 브리지 게이트웨이 탐색 
DEFAULT_GW=$(ip route | grep "default" | head -1 | awk '{print $3}')
DEFAULT_DEV=$(ip route | grep "default" | head -1 | awk '{print $5}')

# 도커 컨테이너 안에서(도커 내부에서는 이미 tailscale로 연결된 상태여서 100.x.x.x임) 
# 라즈베리파이에서 실제로 나가는 출구ip를 찾고 저장하는 명령어
# 실제 lan (물리적)대역으로 나가도록 저장함

# ip route : 라우팅 테이블 확인
# grep "default" : default(기본 트래픽)로 시작하는 줄 찾기
# head -1 : 첫 번째 줄만 선택
# awk '{print $3}' : 세 번째 열(게이트웨이) 출력
# awk '{print $5}' : 다섯 번째 열(인터페이스) 출력



if [ -n "$DEFAULT_GW" ]; then
    echo "기본 게이트웨이: ${DEFAULT_GW} (via ${DEFAULT_DEV})"

    # 타겟팅된 로컬망 라우팅만 우회 시키기
    # 젯슨에서 통신 할 로컬망 대역.
    # TARGET_SUBNET="--" .env에서 설정
    
    # .env에서 LOCAL_SUBNET을 넘겨준 경우 그것을 최우선으로 사용
    if [ -n "$LOCAL_SUBNET" ]; then
        TARGET_SUBNET="$LOCAL_SUBNET"
    fi

    # 라우팅 규칙 추가
    ip route add "$TARGET_SUBNET" via "$DEFAULT_GW" dev "$DEFAULT_DEV" 2>/dev/null || true
    # 라우팅 테이블에 추가 
    # $TARGET_SUBNET이 들어오면
    #  $DEFAULT_GW 여기로 나가도록(실제 라즈베리파이 lan)
    #  2>/dev/null || true 에러처리

    echo "로컬망 우회 완료: ${TARGET_SUBNET} → ${DEFAULT_GW}"
else
    echo "⚠️ 기본 게이트웨이를 찾을 수 없습니다. (네트워크 상태 확인 필요)"
fi

echo ""
echo "📋 최종 라우팅 테이블 확인:"
ip route
echo ""

# 컨테이너 생존 유지
wait $TAILSCALED_PID
