import cv2
import base64
import numpy as np
import os

class CameraSystem:
    def __init__(self, camera_index=0, width=640, height=480):
        self.camera_index = camera_index
        self.width = width
        self.height = height
        self.cap = None
        self._connect()

    def _connect(self):
        self.cap = cv2.VideoCapture(self.camera_index)
        
        if not self.cap.isOpened():
            print(f"Error: 카메라({self.camera_index})를 열 수 없습니다.")
            return

        # --- 카메라 설정 (한 번만 적용) ---
        self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1) 
        self.cap.set(cv2.CAP_PROP_EXPOSURE, 60)    
        self.cap.set(cv2.CAP_PROP_BRIGHTNESS, 0)  
        
        # 2. 해상도 설정 (원본 캡처용)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        

    def capture_jpeg(self):
        """
        1. 이미지 캡처
        2. 중앙 320x240 크롭
        3. 위아래 40px 검은색 패딩 -> 320x320 정사각형
        4. 640x640으로 2배 확대 (업스케일링)
        5. Base64 인코딩 후 반환
        """
        
        # 연결 상태 확인 및 재연결
        if self.cap is None or not self.cap.isOpened():
            print("CameraSystem: 재연결 시도 중...")
            self._connect()
            if not self.cap.isOpened():
                return "ERROR"

        # 버퍼 비우기 (지연 시간 최소화)
        for _ in range(15):
            self.cap.grab()

        ret, frame = self.cap.read()

        success, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 100])
        
        if success:
            jpg_as_text = base64.b64encode(buffer).decode('utf-8')
            return jpg_as_text
        else:
            return "ERROR"
       
        
        
        

        if not ret:
            print("CameraSystem: 프레임 읽기 실패")
            return "ERROR"

        try:
            # ==========================================
            # [Step 1] 중앙 크롭 (320x240)
            # ==========================================
            h, w = frame.shape[:2] 
            crop_w = 320
            crop_h = 240

            center_x = w // 2
            center_y = h // 2
            
            # 자르기 시작할 좌상단 좌표
            start_x = center_x - (crop_w // 2)
            start_y = center_y - (crop_h // 2)
            
            # 자르기 끝낼 우하단 좌표
            end_x = start_x + crop_w
            end_y = start_y + crop_h

            # 이미지 자르기 (결과: 320x240)
            cropped_frame = frame[start_y:end_y, start_x:end_x]

            # ==========================================
            # [Step 2] 320x320 정사각형 만들기 (블랙 패딩)
            # ==========================================
            # 현재 240 높이를 320으로 만들기 위해 위아래 총 80px 필요
            top_pad = 40
            bottom_pad = 40
            left_pad = 0
            right_pad = 0

            # 검은색(0,0,0)으로 테두리 채우기 (결과: 320x320)
            padded_frame = cv2.copyMakeBorder(
                cropped_frame, 
                top_pad, bottom_pad, left_pad, right_pad, 
                cv2.BORDER_CONSTANT, 
                value=[0, 0, 0]
            )

            # ==========================================
            # [Step 3] 640x640으로 업스케일링 (2배 확대)
            # ==========================================
            target_size = (640, 640)
            
            # INTER_CUBIC: 확대 시 화질 저하를 줄여주는 보간법
            upscaled_frame = cv2.resize(
                padded_frame, 
                target_size, 
                interpolation=cv2.INTER_CUBIC
            )

            # 최종 처리된 이미지
            final_image = upscaled_frame

        except Exception as e:
            print(f"Image Processing Error: {e}")
            return "ERROR"

        # ==========================================
        # [Step 4] JPG 인코딩 및 Base64 변환
        # ==========================================
        success, buffer = cv2.imencode('.jpg', final_image, [int(cv2.IMWRITE_JPEG_QUALITY), 100])
        
        if success:
            jpg_as_text = base64.b64encode(buffer).decode('utf-8')
            return jpg_as_text
        else:
            return "ERROR"

    def release(self):
        """자원 해제"""
        if self.cap and self.cap.isOpened():
            self.cap.release()
            print("CameraSystem: 카메라 자원 해제 완료")
