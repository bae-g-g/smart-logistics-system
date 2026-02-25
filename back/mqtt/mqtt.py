"""MQTT Service for communication with Raspberry Pi IoT devices."""

import json
import logging
import ssl
import threading
from typing import Callable, Optional, Any
from datetime import datetime

import paho.mqtt.client as mqtt

from app.config import get_settings
from app.services.websocket import manager as ws_manager

logger = logging.getLogger(__name__)
settings = get_settings()


class MQTTService:
    """MQTT Client service for subscribing to IoT device messages."""
    
    def __init__(self):
        self.client: Optional[mqtt.Client] = None
        self.connected: bool = False
        self._message_handlers: dict[str, list[Callable]] = {}
        self._thread: Optional[threading.Thread] = None
    
    def connect(self) -> bool:
        """Connect to the MQTT broker."""
        if not settings.MQTT_ENABLED:
            logger.info("MQTT is disabled in settings")
            return False
        
        try:
            # Create MQTT client with protocol v5
            self.client = mqtt.Client(
                client_id=settings.MQTT_CLIENT_ID,
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2
            )
            
            # Set callbacks
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            self.client.on_message = self._on_message
            
            # Set authentication if provided
            if settings.MQTT_USERNAME and settings.MQTT_PASSWORD:
                self.client.username_pw_set(
                    settings.MQTT_USERNAME,
                    settings.MQTT_PASSWORD
                )
            
            # Configure TLS if enabled
            if settings.MQTT_USE_TLS:
                self._configure_tls()
            
            # Connect to broker
            tls_status = "TLS" if settings.MQTT_USE_TLS else "non-TLS"
            logger.info(
                f"Connecting to MQTT broker at "
                f"{settings.MQTT_BROKER_HOST}:{settings.MQTT_BROKER_PORT} ({tls_status})"
            )
            
            # Retry logic for connection
            import time
            max_retries = 5
            retry_delay = 5
            
            for attempt in range(max_retries):
                try:
                    self.client.connect(
                        settings.MQTT_BROKER_HOST,
                        settings.MQTT_BROKER_PORT,
                        keepalive=60
                    )
                    logger.info("Successfully initiated connection to MQTT broker")
                    break
                except Exception as e:
                    if attempt < max_retries - 1:
                        logger.warning(f"Connection attempt {attempt + 1} failed: {e}. Retrying in {retry_delay}s...")
                        time.sleep(retry_delay)
                    else:
                        raise e
            
            # Start the loop in a background thread
            self.client.loop_start()
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker after multiple attempts: {e}")
            return False
    
    def _configure_tls(self):
        """Configure TLS settings for secure connection."""
        try:
            # Create SSL context
            ssl_context = ssl.create_default_context()
            
            # Load CA certificate if provided
            if settings.MQTT_CA_CERT:
                ssl_context.load_verify_locations(settings.MQTT_CA_CERT)
                logger.info(f"Loaded CA certificate: {settings.MQTT_CA_CERT}")
            
            # Load client certificate and key if provided (mutual TLS)
            if settings.MQTT_CLIENT_CERT and settings.MQTT_CLIENT_KEY:
                ssl_context.load_cert_chain(
                    certfile=settings.MQTT_CLIENT_CERT,
                    keyfile=settings.MQTT_CLIENT_KEY
                )
                logger.info("Loaded client certificate for mutual TLS")
            
            # Set hostname verification
            if settings.MQTT_TLS_INSECURE:
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
                logger.warning("TLS hostname verification disabled (insecure)")
            
            # Apply TLS configuration
            self.client.tls_set_context(ssl_context)
            logger.info("TLS configuration applied successfully")
            
        except Exception as e:
            logger.error(f"Failed to configure TLS: {e}")
            raise
    
    def disconnect(self):
        """Disconnect from the MQTT broker."""
        if self.client:
            logger.info("Disconnecting from MQTT broker")
            self.client.loop_stop()
            self.client.disconnect()
            self.connected = False
            self.client = None
    
    def _on_connect(self, client, userdata, flags, reason_code, properties):
        """Callback when connected to MQTT broker."""
        if reason_code == 0:
            self.connected = True
            logger.info("Connected to MQTT broker successfully")
            
            # Subscribe to all topics under the prefix
            topic = f"{settings.MQTT_TOPIC_PREFIX}/#"
            client.subscribe(topic)
            logger.info(f"Subscribed to topic: {topic}")
        else:
            logger.error(f"Failed to connect to MQTT broker: {reason_code}")
    
    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        """Callback when disconnected from MQTT broker."""
        self.connected = False
        logger.warning(f"Disconnected from MQTT broker: {reason_code}")
    
    def _on_message(self, client, userdata, msg):
        """Callback when a message is received."""
        try:
            topic = msg.topic
            payload = msg.payload.decode('utf-8')
            
            logger.debug(f"Received message on {topic}: {payload}")
            
            # Parse JSON payload
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                data = {"raw": payload}
            
            # Add metadata
            message = {
                "topic": topic,
                "data": data,
                "timestamp": datetime.now().isoformat()
            }
            
            # Call registered handlers for this topic
            self._dispatch_message(topic, message)
            
            # Broadcast to WebSocket clients
            self._broadcast_to_websocket(message)
            
        except Exception as e:
            logger.error(f"Error processing MQTT message: {e}")
    
    def _dispatch_message(self, topic: str, message: dict):
        """Dispatch message to registered handlers."""
        # Check exact topic match
        if topic in self._message_handlers:
            for handler in self._message_handlers[topic]:
                try:
                    handler(message)
                except Exception as e:
                    logger.error(f"Error in message handler: {e}")
        
        # Check wildcard matches (e.g., "autobox/sensor/#")
        for pattern, handlers in self._message_handlers.items():
            if self._topic_matches(pattern, topic):
                for handler in handlers:
                    try:
                        handler(message)
                    except Exception as e:
                        logger.error(f"Error in message handler: {e}")
    
    def _topic_matches(self, pattern: str, topic: str) -> bool:
        """Check if a topic matches a pattern with wildcards."""
        if pattern == topic:
            return False  # Already handled in exact match
        
        pattern_parts = pattern.split('/')
        topic_parts = topic.split('/')
        
        for i, part in enumerate(pattern_parts):
            if part == '#':
                return True  # Multi-level wildcard matches everything after
            if part == '+':
                continue  # Single-level wildcard matches any single level
            if i >= len(topic_parts) or part != topic_parts[i]:
                return False
        
        return len(pattern_parts) == len(topic_parts)
    
    def _broadcast_to_websocket(self, message: dict):
        """Broadcast MQTT message to WebSocket clients."""
        import asyncio
        
        try:
            # Create async task to broadcast
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(
                ws_manager.broadcast({
                    "type": "mqtt_message",
                    "payload": message
                })
            )
            loop.close()
        except Exception as e:
            logger.debug(f"Could not broadcast to WebSocket: {e}")
    
    def publish(self, topic: str, payload: Any, qos: int = 0, retain: bool = False) -> bool:
        """Publish a message to the MQTT broker."""
        if not self.client or not self.connected:
            logger.warning("Cannot publish: not connected to MQTT broker")
            return False
        
        try:
            # Convert payload to JSON string if it's a dict
            if isinstance(payload, dict):
                payload = json.dumps(payload)
            
            full_topic = f"server_msg/{topic}"
            result = self.client.publish(full_topic, payload, qos=qos, retain=retain)
            
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.debug(f"Published to {full_topic}: {payload}")
                return True
            else:
                logger.error(f"Failed to publish message: {result.rc}")
                return False
                
        except Exception as e:
            logger.error(f"Error publishing MQTT message: {e}")
            return False
    
    def subscribe(self, topic: str, handler: Callable[[dict], None]):
        """Register a handler for a specific topic."""
        full_topic = f"{settings.MQTT_TOPIC_PREFIX}/{topic}"
        
        if full_topic not in self._message_handlers:
            self._message_handlers[full_topic] = []
        
        self._message_handlers[full_topic].append(handler)
        logger.info(f"Registered handler for topic: {full_topic}")
    
    def unsubscribe(self, topic: str, handler: Callable[[dict], None]):
        """Remove a handler for a specific topic."""
        full_topic = f"{settings.MQTT_TOPIC_PREFIX}/{topic}"
        
        if full_topic in self._message_handlers:
            if handler in self._message_handlers[full_topic]:
                self._message_handlers[full_topic].remove(handler)
    
    @property
    def is_connected(self) -> bool:
        """Check if connected to MQTT broker."""
        return self.connected


# Global MQTT service instance
mqtt_service = MQTTService()


# Example message handlers
def handle_sensor_data(message: dict):
    """Handle sensor data from IoT devices."""
    logger.info(f"Sensor data received: {message}")
    
    # Store sensor data in database
    try:
        from app.database import SessionLocal
        from app.models.vehicle import SensorStatus
        
        data = message.get("data", {})
        if not data:
            return
        
        vehicle_id = data.get("vehicle_id", "AGV-001")
        
        db = SessionLocal()
        try:
            # Handle individual sensor update
            if "sensor_name" in data:
                sensor = db.query(SensorStatus).filter(
                    SensorStatus.vehicle_id == vehicle_id,
                    SensorStatus.sensor_name == data["sensor_name"]
                ).first()
                
                if sensor:
                    sensor.status = data.get("status", "ok")
                    sensor.value = data.get("value")
                    sensor.health = data.get("health", 100)
                    sensor.data = data.get("data")
                else:
                    sensor = SensorStatus(
                        vehicle_id=vehicle_id,
                        sensor_name=data["sensor_name"],
                        sensor_type=data.get("sensor_type"),
                        status=data.get("status", "ok"),
                        value=data.get("value"),
                        health=data.get("health", 100),
                        data=data.get("data")
                    )
                    db.add(sensor)
                
                db.commit()
                logger.info(f"Sensor status updated: {vehicle_id}/{data['sensor_name']}")
            
            # Handle bulk sensor update (multiple sensors in one message)
            elif "sensors" in data:
                for sensor_data in data["sensors"]:
                    sensor = db.query(SensorStatus).filter(
                        SensorStatus.vehicle_id == vehicle_id,
                        SensorStatus.sensor_name == sensor_data["name"]
                    ).first()
                    
                    if sensor:
                        sensor.status = sensor_data.get("status", "ok")
                        sensor.value = sensor_data.get("value")
                        sensor.health = sensor_data.get("health", 100)
                    else:
                        sensor = SensorStatus(
                            vehicle_id=vehicle_id,
                            sensor_name=sensor_data["name"],
                            sensor_type=sensor_data.get("type"),
                            status=sensor_data.get("status", "ok"),
                            value=sensor_data.get("value"),
                            health=sensor_data.get("health", 100)
                        )
                        db.add(sensor)
                
                db.commit()
                logger.info(f"Bulk sensor status updated for: {vehicle_id}")
                
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Error storing sensor data: {e}")


def handle_vehicle_position(message: dict):
    """Handle vehicle position updates from IoT devices."""
    logger.info(f"Vehicle position received: {message}")
    
    # Store vehicle position in database
    try:
        from app.database import SessionLocal
        from app.models.vehicle import VehiclePosition
        
        data = message.get("data", {})
        if not data:
            return
        
        vehicle_id = data.get("vehicle_id", "AGV-001")
        
        db = SessionLocal()
        try:
            # Find existing position record or create new one
            position = db.query(VehiclePosition).filter(
                VehiclePosition.vehicle_id == vehicle_id
            ).first()
            
            if position:
                position.x = data.get("x", position.x)
                position.y = data.get("y", position.y)
                position.angle = data.get("angle", position.angle)
                position.speed = data.get("speed", position.speed)
                position.battery = data.get("battery", position.battery)
                position.mode = data.get("mode", position.mode)
            else:
                position = VehiclePosition(
                    vehicle_id=vehicle_id,
                    x=data.get("x", 0),
                    y=data.get("y", 0),
                    angle=data.get("angle", 0),
                    speed=data.get("speed", 0),
                    battery=data.get("battery", 100),
                    mode=data.get("mode", "IDLE")
                )
                db.add(position)
            
            db.commit()
            logger.info(f"Vehicle position updated: {vehicle_id} at ({position.x}, {position.y})")
            
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Error storing vehicle position: {e}")


def handle_device_status(message: dict):
    """Handle device status updates."""
    logger.info(f"Device status update: {message}")
    
    # Store device status in database
    try:
        from app.database import SessionLocal
        from app.models.device import DeviceStatus, OperationStatus
        
        data = message.get("data", {})
        if not data:
            return
        
        device_id = data.get("device_id")
        if not device_id:
            return
        
        db = SessionLocal()
        try:
            device = db.query(DeviceStatus).filter(
                DeviceStatus.device_id == device_id
            ).first()
            
            if device:
                device.battery_level = data.get("battery_level", device.battery_level)
                device.is_connected = data.get("is_connected", device.is_connected)
                device.cpu_temperature = data.get("cpu_temperature")
                device.location = data.get("location")
                if "operation_status" in data:
                    device.operation_status = OperationStatus(data["operation_status"])
            else:
                device = DeviceStatus(
                    device_id=device_id,
                    battery_level=data.get("battery_level", 0),
                    is_connected=data.get("is_connected", True),
                    cpu_temperature=data.get("cpu_temperature"),
                    location=data.get("location"),
                    operation_status=OperationStatus(data.get("operation_status", "STOP"))
                )
                db.add(device)
            
            db.commit()
            logger.info(f"Device status updated: {device_id}")
            
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Error storing device status: {e}")


def handle_alert_notification(message: dict):
    """Handle alert notifications from devices."""
    logger.info(f"Alert notification: {message}")
    
    # Create alert record in database
    try:
        from app.database import SessionLocal
        from app.models.alert import Alert, AlertSeverity
        
        data = message.get("data", {})
        if not data:
            return
        
        db = SessionLocal()
        try:
            alert = Alert(
                alert_type=data.get("alert_type", "system"),
                severity=AlertSeverity(data.get("severity", "info")),
                title=data.get("title", "시스템 알림"),
                message=data.get("message", ""),
                source_type=data.get("source_type"),
                source_id=data.get("source_id")
            )
            db.add(alert)
            db.commit()
            logger.info(f"Alert created: {alert.alert_id}")
            
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Error creating alert: {e}")


def handle_box_image(message: dict):
    """Handle box image data from Raspberry Pi.
    
    Expected message format from Raspberry Pi:
    Topic: factory_msg/command/box_img
    Payload: {"dest": "base64_encoded_image_data"}
    """
    logger.info(f"Box image data received from topic: {message.get('topic')}")
    
    try:
        data = message.get("data", {})
        if not data:
            logger.warning("Empty data received in box_img message")
            return
        
        # 라즈베리 파이에서 보내는 형식: {"dest": base64_image}
        image_base64 = data.get("dest")
        
        if not image_base64:
            logger.warning("No 'dest' key found in box_img message")
           
        
        logger.info(f"Box image received - base64 length: {len(image_base64) if image_base64 else 0} characters")
        
        # 데이터 저장 로직
        import os
        
        # 저장 디렉토리 설정 (Docker Volume: /app/data -> Host: ./backend/data)
        save_dir = "./data"
        
        # 디렉토리가 없으면 생성
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
            logger.info(f"Created directory: {save_dir}")
            
        # 파일명 생성
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        filename = f"{save_dir}/box_img_{timestamp}.json"
        
        # JSON 파일 저장
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
            
        logger.info(f"Saved box image data to {filename}")

    except Exception as e:
        logger.error(f"Error processing box image: {e}")


# ============================================
# RC 상태 이름 설정 (라즈베리파이의 실제 상태명으로 수정하세요)
# ============================================
RC_STATE_DELIVERING = "DELIVERING"       # ← 배송 출발 시 RC 상태 (MOVING 전이 트리거)
RC_STATE_READY_TO_LOAD = "READY_TO_LOAD" # ← 복귀 완료 시 RC 상태 (COMPLETED 전이 트리거)
RC_STATE_RETURNING = "RETURNING"         # ← 복귀 중 RC 상태 (즉시 COMPLETED 전이 트리거)

# Module-level variable to track previous RC state for transition detection
_prev_rc_state = None


def _auto_start_oldest_ready():
    """Find the oldest READY logistics item (today) and mark it as MOVING."""
    try:
        from app.database import SessionLocal
        from app.models.waybill import LogisticsItem, LogisticsStatus, WaybillMap
        from sqlalchemy import func
        import asyncio

        db = SessionLocal()
        try:
            item = db.query(LogisticsItem).filter(
                LogisticsItem.status == LogisticsStatus.READY,
            ).order_by(LogisticsItem.created_at.asc()).first()

            if not item:
                logger.info("No READY waybill found to start delivery")
                return

            now = datetime.now()
            item.status = LogisticsStatus.MOVING
            item.updated_at = now
            db.commit()

            mapping = db.query(WaybillMap).filter(
                WaybillMap.tracking_number == item.tracking_number
            ).first()
            waybill_id = mapping.waybill_id if mapping else None

            logger.info(
                f"Auto-started delivery: {item.tracking_number} "
                f"(ID={waybill_id}, dest={item.destination}) → MOVING"
            )

            if waybill_id:
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(
                        ws_manager.broadcast({
                            "type": "waybill_update",
                            "data": {
                                "waybill_id": waybill_id,
                                "tracking_number": item.tracking_number,
                                "status": "MOVING",
                                "destination": item.destination
                            }
                        })
                    )
                    loop.close()
                except Exception as ws_err:
                    logger.debug(f"Could not broadcast auto-start: {ws_err}")

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error in auto-start: {e}")


def _auto_complete_oldest_moving():
    """Find the oldest MOVING logistics item (today) and mark it as COMPLETED."""
    try:
        from app.database import SessionLocal
        from app.models.waybill import LogisticsItem, LogisticsStatus, WaybillMap
        from sqlalchemy import func
        import asyncio

        db = SessionLocal()
        try:
            item = db.query(LogisticsItem).filter(
                LogisticsItem.status == LogisticsStatus.MOVING,
            ).order_by(LogisticsItem.created_at.asc()).first()

            if not item:
                logger.info("No MOVING waybill found to auto-complete")
                return

            now = datetime.now()
            item.status = LogisticsStatus.COMPLETED
            item.completed_at = now
            item.updated_at = now
            db.commit()

            mapping = db.query(WaybillMap).filter(
                WaybillMap.tracking_number == item.tracking_number
            ).first()
            waybill_id = mapping.waybill_id if mapping else None

            logger.info(
                f"Auto-completed waybill: {item.tracking_number} "
                f"(ID={waybill_id}, dest={item.destination})"
            )

            if waybill_id:
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(
                        ws_manager.broadcast({
                            "type": "waybill_update",
                            "data": {
                                "waybill_id": waybill_id,
                                "tracking_number": item.tracking_number,
                                "status": "COMPLETED",
                                "destination": item.destination
                            }
                        })
                    )
                    loop.close()
                except Exception as ws_err:
                    logger.debug(f"Could not broadcast auto-complete: {ws_err}")

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error in auto-complete: {e}")


def handle_rc_state(message: dict):
    """Handle RC state data from Raspberry Pi.
    
    Expected message format from Raspberry Pi:
    Topic: factory_msg/state/rc
    Payload: JSON data containing RC state information
    
    Saves received data to backend/logs/rc_state_latest.json (single file, overwritten).
    Detects state transitions:
      - → DELIVERING:    oldest READY  → MOVING    (배송 시작)
      - → READY_TO_LOAD: oldest MOVING → COMPLETED (배송 완료)
    """
    global _prev_rc_state
    logger.debug(f"RC state data received from topic: {message.get('topic')}")
    
    try:
        data = message.get("data", {})
        if not data:
            logger.warning("Empty data received in state/rc message")
            return
        
        logger.debug(f"RC state received: {data}")
        
        # Detect state transitions
        current_state = data.get("state")
        if current_state != _prev_rc_state:
            # DELIVERING → auto-start: READY → MOVING
            if current_state == RC_STATE_DELIVERING and _prev_rc_state != RC_STATE_DELIVERING:
                logger.info(f"State transition: {_prev_rc_state} → {RC_STATE_DELIVERING}")
                _auto_start_oldest_ready()
            
            # READY_TO_LOAD → auto-complete: MOVING → COMPLETED
            elif current_state == RC_STATE_READY_TO_LOAD and _prev_rc_state != RC_STATE_READY_TO_LOAD:
                logger.info(f"State transition: {_prev_rc_state} → {RC_STATE_READY_TO_LOAD}")
                _auto_complete_oldest_moving()
            
            # RETURNING → auto-complete: MOVING → COMPLETED (즉시 완료 처리)
            elif current_state == RC_STATE_RETURNING and _prev_rc_state != RC_STATE_RETURNING:
                logger.info(f"State transition: {_prev_rc_state} → {RC_STATE_RETURNING}")
                _auto_complete_oldest_moving()
        _prev_rc_state = current_state
        
        # 데이터 저장 로직
        import os
        
        # 저장 디렉토리 설정 (Docker Volume: /app/logs -> Host: ./backend/logs)
        save_dir = "./logs"
        
        # 디렉토리가 없으면 생성
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
            logger.info(f"Created directory: {save_dir}")
            
        # 단일 파일로 저장 (덮어쓰기) - 저장소 최적화
        filename = f"{save_dir}/rc_state_latest.json"
        
        # 전체 메시지 구조 저장 (topic, data, timestamp 포함)
        save_data = {
            "topic": message.get("topic"),
            "data": data,
            "received_at": message.get("timestamp"),
            "saved_at": datetime.now().isoformat()
        }
        
        # JSON 파일 저장 (덮어쓰기)
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(save_data, f, ensure_ascii=False, indent=4)

    except Exception as e:
        logger.error(f"Error processing RC state: {e}")


# Register default handlers
def register_default_handlers():
    """Register default message handlers."""
    mqtt_service.subscribe("sensor/#", handle_sensor_data)
    mqtt_service.subscribe("vehicle/position", handle_vehicle_position)
    mqtt_service.subscribe("vehicle/#", handle_vehicle_position)
    mqtt_service.subscribe("device/status", handle_device_status)
    mqtt_service.subscribe("alert/#", handle_alert_notification)
    mqtt_service.subscribe("command/box_img", handle_box_image)
    mqtt_service.subscribe("state/rc", handle_rc_state)
