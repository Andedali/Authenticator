import cv2
from pyzbar.pyzbar import decode
import numpy as np

def scan_qr_aggressive():
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
    cap.set(cv2.CAP_PROP_EXPOSURE, -6)
    
    print("Нажмите 'q' для выхода")
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        # === АГРЕССИВНАЯ ПРЕДОБРАБОТКА ===
        # 1. Конвертация в оттенки серого
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # 2. Сильное уменьшение яркости
        gray = cv2.multiply(gray, 0.6)
        gray = np.clip(gray, 0, 255).astype(np.uint8)
        
        # 3. Адаптивная бинаризация (критично для экранов!)
        binary = cv2.adaptiveThreshold(
            gray, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            11, 2
        )
        
        # 4. Морфологические операции (убираем шум)
        kernel = np.ones((3, 3), np.uint8)
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
        
        # 5. Размытие для удаления муара
        binary = cv2.GaussianBlur(binary, (5, 5), 0)
        
        # === ПОПЫТКА РАСПОЗНАВАНИЯ ===
        # Пробуем на обработанном изображении
        qr_codes = decode(binary)
        
        # Если не вышло, пробуем оригинал
        if not qr_codes:
            qr_codes = decode(frame)
        
        # === ОТОБРАЖЕНИЕ ===
        for qr in qr_codes:
            qr_data = qr.data.decode('utf-8')
            points = qr.polygon
            
            if len(points) == 4:
                pts = np.array([point for point in points], dtype=np.int32)
                pts = pts.reshape((-1, 1, 2))
                cv2.polylines(frame, [pts], True, (0, 255, 0), 3)
                cv2.putText(frame, qr_data[:25], (pts[0][0][0], pts[0][0][1] - 10),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                print(f"✅ QR: {qr_data}")
        
        cv2.imshow('QR Scanner (Aggressive)', frame)
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    
    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    scan_qr_aggressive()