# main.py
import time
from state import SystemState
from network_manager import local_Network
from network_manager import server_Network
from conveyer_control import ConveyerController
from conveyer_belt_cam import CameraSystem

# 1. 시스템 초기화
state = SystemState()
server_network = server_Network(state)
local_network = local_Network(state,server_network)
conveyer = ConveyerController()
camera = CameraSystem()
reset = False

class SystemReset(Exception):
    pass

def check_reset():
    if state.reset:
        raise SystemReset("리셋 신호 감지됨!")



def run_cycle():
    try:
            
        """박스 하나를 처리하는 전체 공정"""
        print(f"\n  시작 (남은 박스: {state.box_count})")
        
        
        print("1 컨베이어 가동")
        conveyer.belt_run_until_sensor()
        conveyer.red_led()

        while not conveyer.box_detected_flag:
            check_reset()
            time.sleep(0.1)

        print("3 컨베이어 정지")
        conveyer.blue_led()
        time.sleep(1.5) # 박스 흔들림 대기 
        check_reset()

        print("3 카메라 촬영 및 전송")
        captured_img = camera.capture_jpeg()
        server_network.send_command("factory_msg/command/box_img" ,{"dest":captured_img})

        check_reset()

        print("4 RC카 호출 중...")
        while not state.parking_done or not state.destination :
            check_reset()
            print("rc카 주차 대기 중")
            print(state.parking_done)
            print(state.destination)
            
            local_network.send_command("factory_msg/rc1/command", {"cmd" : "COME_HERE"})
            time.sleep(2) # rc카에서  "edge_msg/rc1/command","cmd:parking" 형식으로 보내줌 =>parking_done= Ture
            
        conveyer.red_led()
        print("5 적재 시작 (Push)")
        conveyer.push_box()
        check_reset()
        local_network.send_command(
            f"factory_msg/{state.rc_car_id}/command",
            {
                "cmd" : "GO_DEST",
                "target": state.destination,
            }
            )

        print("6 one_cycle ")
        state.one_cycle()
        check_reset()
        '''
        server_network.send_event_to_server({
            
            "event": "process_done", 
            "box_cnt" : state.box_count,
            "dest": state.destination,
            "rc_car_id" : state.rc_car_id
        })
        '''
    except SystemReset:
        
        conveyer.emergency_stop() 
        state.reset_all()  

        return  
 

def main():
    try:
        print("=== 팩토리 시스템 가동 ===")
        state.box_count = 0

        while True:
            if state.box_count >= 1:
                run_cycle()
            else:
                print("대기 중,박스 없음")
                conveyer.green_led()
                time.sleep(1)
                
    except KeyboardInterrupt:
        print("시스템 종료")
        conveyer.cleanup()
        local_network.cleanup()
        server_network.cleanup()

if __name__ == "__main__":
    main()
