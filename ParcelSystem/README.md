# ParcelSystem-MVP-prototype

## ความต้องการพื้นฐาน
- Python 3.10+
- pip
- (สำหรับ build) PyInstaller, Inno Setup (Windows)

## ขั้นตอนรันแบบไม่แพ็ก (พัฒนา/ทดสอบ)

### รัน Server (โฟลเดอร์ server)

1. สร้าง virtualenv และติดตั้ง

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

2. รัน server

```powershell
python -m server.app.main
```

Server จะเริ่ม uvicorn ที่พอร์ต 8000 และเริ่ม broadcast UDP เพื่อให้ client หาเจอ

### รัน Client (โฟลเดอร์ client)

1. สร้าง virtualenv และติดตั้ง

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

2. รัน client

```powershell
python client_app.py
```

เมื่อ client พบ broadcast ของ server จะเติม `Server:` ใน UI ให้ และสามารถสแกน/พิมพ์เลข tracking แล้วส่งได้

## แพ็กเป็น .exe (ขั้นตอนแบบสั้น)

1. ติดตั้ง PyInstaller

```powershell
pip install pyinstaller
```

2. แพ็ก Server

```powershell
pyinstaller --onefile --name ParcelServer server/app/main.py
```

3. แพ็ก Client

```powershell
pyinstaller --onefile --windowed --name ParcelClient client/client_app.py
```

4. สร้าง Installer โดยใช้ Inno Setup: ใช้ `build\inno_setup_installer.iss` แล้วคอมไพล์เป็น `ParcelSystem_Installer.exe`

## หมายเหตุเพิ่มเติม
- Prototype นี้ใช้ SQLite เป็น storage (embedded) — server process เป็นผู้เขียนไฟล์ DB เท่านั้น จึงปลอดภัยจาก conflict
- หากต้องการให้ server รันอัตโนมัติเมื่อเครื่องเปิด คุณสามารถลงทะเบียน `ParcelServer.exe` เป็น Windows Service ด้วย `nssm` (หรือใช้ Inno Setup to run it once postinstall)