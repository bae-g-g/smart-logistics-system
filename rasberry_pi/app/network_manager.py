# network_manager.py
import paho.mqtt.client as mqtt
import json
import ssl
import os
from dotenv import load_dotenv


dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
load_dotenv(dotenv_path)

class local_Network:
    def __init__(self, state,server_Network_instance):
        self.state = state 
        self.server_Net =server_Network_instance
        
        self.client_local = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client_local.on_message = self.on_local_message
        self.client_local.connect("localhost", 1883) # localhost로 통신 (실제로컬ip -> 라우팅 -> tailscale -> localhost)
        self.client_local.subscribe("edge_msg/+/+")
        self.client_local.loop_start()

       

    def on_local_message(self, client, userdata, msg):
        try:
            
            topic_parts = msg.topic.split('/')
            

            if topic_parts[2] == "command":
                payload = json.loads(msg.payload.decode())

                print(msg.topic) 
                print(payload)
                
                if payload.get("cmd", 0) == "ready":  # rc카 호출
                    self.state.rc_car_id = topic_parts[1]
                    self.state.rc_car_ready = 1

                elif payload.get("cmd", 0) == "ARRIVED": # 주차 완료
                    self.state.parking_done = True

                elif payload.get("cmd", 0) == "RESET":
                    self.state.reset = True

                else:
                    1
                    
            if  topic_parts[2] == "state":
                self.server_Net.send_state("factory_msg/state/rc",msg.payload)

        except:
            pass

    # --- 전송 함수들 ---
    def send_command(self, topic, data):
        print(topic)
        print(data)
        self.client_local.publish(topic, json.dumps(data))
        
    def send_state(self, topic, data):
        self.client_local.publish(topic, json.dumps(data))
    
    def cleanup(self):
        self.client_local.loop_stop()



class server_Network:
    def __init__(self, state):
        self.state = state # 상태판 공유
        

        self.server_ip = os.getenv("SERVER_IP")
        self.server_port = int(os.getenv("SERVER_PORT", 8883))
        self.username = os.getenv("SERVER_MQTT_USER")
        self.password = os.getenv("SERVER_MQTT_PASS")

    
        # --- 2. 서버 클라이언트 (EC2) ---
        self.client_server = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client_server.on_connect = self.on_server_connect
        self.client_server.on_message = self.on_server_message

        self.setup_tls()
        
        self.client_server.connect(self.server_ip, self.server_port)
        self.client_server.loop_start()

    def setup_tls(self):
        self.client_server.username_pw_set(self.username, self.password)
        ca_cert = "/certs/ca.crt"
        client_cert = "/certs/client.crt"
        client_key = "/certs/client.key"

        if os.path.exists(ca_cert):
            try:
                self.client_server.tls_set(
                    ca_certs=ca_cert, certfile=client_cert, keyfile=client_key,
                    cert_reqs=ssl.CERT_NONE, tls_version=ssl.PROTOCOL_TLSv1_2
                )
                self.client_server.tls_insecure_set(True)
                print("✅ TLS 설정 완료")
            except Exception as e:
                print(f"🚨 TLS 설정 에러: {e}")

    # --- 콜백 함수들 ---
    def on_server_connect(self, client, userdata, flags, rc, properties):
        if rc == 0:
            print("✅ EC2 서버 연결 성공")
           
            client.subscribe("server_msg/+/+")

    def on_server_message(self, client, userdata, msg):
        
        try:
            payload = json.loads(msg.payload.decode())
            topic_parts = msg.topic.split('/')
            
            print("recieve_from_server")
            print(payload) 
            
            # 박스 개수 업데이트 명령 수신 시 server_msg/dest/.command/
            if topic_parts[1] == "command":
                if topic_parts[2] == "box-count":
                    if payload.get("box_count", 0) == 100:
                        self.state.reset = True
                    else:
                        self.state.box_count += payload.get("box_count", 0)
                        print(f"📦 박스 개수 갱신: {self.state.box_count}")
                elif topic_parts[2] == "dest":
                    self.state.destination = payload.get("destination", 0)
                    
                elif topic_parts[2] == "dest":
                    if payload.get("destination", 0) == "A" or payload.get("destination", 0) == "B" or payload.get("destination", 0) == "C" or payload.get("destination", 0) == "D" or payload.get("destination", 0) == "E" or payload.get("destination", 0) == "F" :
                        self.state.destination = payload.get("destination", 0)
            
            if  topic_parts[1] == "state":
                1

        except:
            pass


    def send_command(self, topic,data):
        self.client_server.publish(topic, json.dumps(data))

    def send_state(self, topic,data):
        self.client_server.publish(topic, data)

    def cleanup(self):
        self.client_server.loop_stop()


