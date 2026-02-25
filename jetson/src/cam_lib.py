import cv2
import time
import os
from dotenv import load_dotenv

# Load .env
# Helper to find .env
# Structure:
# jetson/
#   .env
#   src/
#     cam_lib.py

# .env is in jetson/ which is parent of src/
dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
load_dotenv(dotenv_path)


class RC_Cam:
    def __init__(self):
        self.PI_IP = os.getenv("PI_IP", "LOCAL_RASPI_IP")
        self.UDP_PORT = int(os.getenv("PI_PORT", 5000))
        self.W = 640
        self.H = 480
        self.FPS = 30
        
        self.frame = None
        self.current_cap = None 
        self.current_idx = -1   
        
        # [중요] 초기화 시점엔 카메라는 안 켭니다 (USB 대역폭 보호)
        
        # GStreamer 파이프라인
        gst_out = (
            f"appsrc ! "
            f"videoconvert ! "
            f"x264enc tune=zerolatency speed-preset=ultrafast bitrate=700 key-int-max=30 ! "
            f"h264parse ! "
            f"mpegtsmux ! " 
            f"udpsink host={self.PI_IP} port={self.UDP_PORT} sync=false"
        )
        
        self.out = cv2.VideoWriter(gst_out, cv2.CAP_GSTREAMER, 0, self.FPS, (self.W, self.H), True)
        if not self.out.isOpened():
            print("❌ [RC_Cam] VideoWriter Failed!")

    def switch_camera(self, cam_idx):
        """
        카메라를 안전하게 전환합니다. (기존 것 끄고 -> 새 것 켬)
        cam_idx: 0 (후방), 1 (전방)
        """
        # 이미 켜진 카메라면 패스
        if self.current_idx == cam_idx and self.current_cap is not None and self.current_cap.isOpened():
            return 

        # 1. 기존 카메라 끄기 (대역폭 확보)
        if self.current_cap is not None:
            self.current_cap.release()
            time.sleep(0.2) # 하드웨어 해제 대기

        # 2. 새 카메라 켜기
        print(f"🔄 [RC_Cam] Switching to Camera {cam_idx}...")
        new_cap = cv2.VideoCapture(cam_idx, cv2.CAP_V4L2)
        
        new_cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.W)
        new_cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.H)
        new_cap.set(cv2.CAP_PROP_FPS, self.FPS)
        
        if new_cap.isOpened():
            # [검증] 실제로 읽히는지 한 프레임 테스트
            ret, _ = new_cap.read()
            if ret:
                self.current_cap = new_cap
                self.current_idx = cam_idx
                print(f"✅ [RC_Cam] Camera {cam_idx} OPEN Success!")
            else:
                print(f"⚠️ [RC_Cam] Camera {cam_idx} Opened but READ Failed (USB Issue?)")
                new_cap.release()
                self.current_cap = None
        else:
            print(f"❌ [RC_Cam] Failed to open Camera {cam_idx}")
            self.current_cap = None

    def get_frame(self):
        if self.current_cap is not None and self.current_cap.isOpened():
            ret, self.frame = self.current_cap.read()
            if ret:
                return True, self.frame
        return False, None

    def stream(self):
        if self.out.isOpened() and self.frame is not None:
            self.out.write(self.frame)

    def release_all(self):
        if self.current_cap is not None:
            self.current_cap.release()
        if self.out.isOpened():
            self.out.release()

