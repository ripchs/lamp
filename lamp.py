import asyncio
import threading
import logging
import webview
from bleak import BleakClient
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

# ===== Настройки =====
ADDRESS = "41:42:AC:A2:76:C9"
CHAR_UUID = "0000fff4-0000-1000-8000-00805f9b34fb"
PC_IP = "127.0.0.1"
PC_PORT = 8000

current_color = [0, 0, 0, 0, 0]
previous_color = [255, 0, 0, 0, 0]

ble_client = None
ble_loop = None

# ===== Логгер =====
log_records = []

class ListHandler(logging.Handler):
    def emit(self, record):
        log_records.append(self.format(record))
        if len(log_records) > 500:
            log_records.pop(0)

logger = logging.getLogger("lamp")
logger.setLevel(logging.DEBUG)
handler = ListHandler()
handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)s  %(message)s", "%H:%M:%S"))
logger.addHandler(handler)


# ===== BLE =====
async def ble_connect():
    global ble_client
    while True:
        try:
            logger.info(f"Подключение к {ADDRESS}…")
            ble_client = BleakClient(ADDRESS)
            await ble_client.connect()
            logger.info("BLE подключён")
            break
        except Exception as e:
            logger.warning(f"Ошибка подключения: {e} — повтор через 2 с")
            await asyncio.sleep(2)


async def ble_write(value):
    global ble_client
    if not ble_client or not ble_client.is_connected:
        logger.warning("BLE отключён, переподключение…")
        await ble_connect()
    try:
        await ble_client.write_gatt_char(CHAR_UUID, bytearray(value))
        logger.debug(f"Отправлено: {value}")
    except Exception as e:
        logger.error(f"Ошибка записи: {e}")
        await ble_connect()
        await ble_client.write_gatt_char(CHAR_UUID, bytearray(value))


def start_ble_loop():
    global ble_loop
    ble_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(ble_loop)
    ble_loop.run_until_complete(ble_connect())
    ble_loop.run_forever()


def send_color(value):
    global current_color, previous_color
    value = [max(0, min(255, v)) for v in value]
    current_color = value
    if value != [0, 0, 0, 0, 0]:
        previous_color = value.copy()
    asyncio.run_coroutine_threadsafe(ble_write(value), ble_loop)


# ===== FastAPI =====
app = FastAPI()

HTML = """<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lamp Control</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    background: #111;
    color: #eee;
    font-family: Arial, sans-serif;
    height: 100vh;
    display: flex;
    flex-direction: column;
    user-select: none;
}

.tabs {
    display: flex;
    background: #1a1a1a;
    border-bottom: 2px solid #2a2a2a;
}
.tab {
    padding: 10px 24px;
    cursor: pointer;
    font-size: 14px;
    color: #888;
    border-bottom: 2px solid transparent;
    margin-bottom: -2px;
    transition: color .2s;
}
.tab.active { color: #fff; border-bottom-color: #4CAF50; }
.tab:hover:not(.active) { color: #bbb; }

.page { display: none; flex: 1; overflow-y: auto; padding: 20px; }
.page.active { display: block; }

.preview {
    width: 100px; height: 100px;
    border-radius: 12px;
    border: 2px solid #333;
    margin: 0 auto 16px;
    transition: background .3s;
}
h3 { font-size: 13px; color: #888; text-transform: uppercase;
     letter-spacing: .05em; margin: 16px 0 6px; }
.row { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
.label { width: 14px; font-size: 13px; color: #aaa; }
input[type=range] { flex: 1; accent-color: #4CAF50; height: 4px; }
.val { width: 44px; font-size: 13px; color: #aaa; text-align: right; }

.presets { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 4px; }
.preset {
    flex: 1; padding: 9px 0;
    border-radius: 8px; border: none;
    background: #222; color: #eee;
    cursor: pointer; font-size: 13px;
    transition: background .15s;
}
.preset:hover { background: #333; }

.btn-apply {
    width: 100%; padding: 12px;
    margin-top: 18px;
    background: #4CAF50; color: white;
    border: none; border-radius: 10px;
    font-size: 15px; cursor: pointer;
    transition: background .15s;
}
.btn-apply:hover { background: #43a047; }
.btn-apply:active { background: #388e3c; }

#logbox {
    background: #0d0d0d;
    border-radius: 8px;
    padding: 10px 12px;
    font-family: monospace;
    font-size: 12px;
    line-height: 1.6;
    height: calc(100vh - 80px);
    overflow-y: auto;
    color: #aaa;
    white-space: pre-wrap;
    word-break: break-all;
}
.log-INFO    { color: #7ec8e3; }
.log-DEBUG   { color: #555; }
.log-WARNING { color: #f0a500; }
.log-ERROR   { color: #e05555; }
</style>
</head>
<body>

<div class="tabs">
  <div class="tab active" onclick="switchTab('ctrl')">Управление</div>
  <div class="tab" onclick="switchTab('logs')">Логи</div>
</div>

<div class="page active" id="ctrl">
  <div class="preview" id="preview"></div>

  <h3>Цвет</h3>
  <div class="row"><span class="label">R</span>
    <input type="range" min="0" max="255" value="255" id="r">
    <span class="val" id="rv">255</span></div>
  <div class="row"><span class="label">G</span>
    <input type="range" min="0" max="255" value="0" id="g">
    <span class="val" id="gv">0</span></div>

  <h3>Температура белого</h3>
  <div class="row">
    <input type="range" min="3000" max="6000" step="100" value="3000" id="white">
    <span class="val" id="wv">3000K</span></div>

  <h3>Яркость</h3>
  <div class="row">
    <input type="range" min="0" max="100" value="100" id="brightness">
    <span class="val" id="bv">100%</span></div>

  <h3>Пресеты</h3>
  <div class="presets">
    <button class="preset" onclick="presetRed()">🔴 Красный</button>
    <button class="preset" onclick="presetGreen()">🟢 Зелёный</button>
    <button class="preset" onclick="presetCold()">⚪ Белый</button>
  </div>

  <button class="btn-apply" onclick="applyColor()">Применить</button>
</div>

<div class="page" id="logs">
  <div id="logbox"></div>
</div>

<script>
let mode = "rg";
const r = document.getElementById("r");
const g = document.getElementById("g");
const white = document.getElementById("white");
const brightness = document.getElementById("brightness");

function switchTab(name) {
    document.querySelectorAll(".tab").forEach((t,i)=>
        t.classList.toggle("active", ["ctrl","logs"][i]===name));
    document.querySelectorAll(".page").forEach(p=>
        p.classList.toggle("active", p.id===name));
    if(name==="logs") loadLogs();
}

function updatePreview() {
    let sc = brightness.value / 100;
    let bg = mode==="rg"
        ? `rgb(${Math.floor(r.value*sc)},${Math.floor(g.value*sc)},0)`
        : (()=>{ let v=Math.floor(255*sc); return `rgb(${v},${v},${v})`; })();
    document.getElementById("preview").style.background = bg;
}

r.oninput = ()=>{ mode="rg"; white.value=3000;
    document.getElementById("rv").innerText=r.value;
    document.getElementById("wv").innerText="3000K"; updatePreview(); };
g.oninput = ()=>{ mode="rg"; white.value=3000;
    document.getElementById("gv").innerText=g.value;
    document.getElementById("wv").innerText="3000K"; updatePreview(); };
white.oninput = ()=>{ mode="white"; r.value=0; g.value=0;
    document.getElementById("rv").innerText="0";
    document.getElementById("gv").innerText="0";
    document.getElementById("wv").innerText=white.value+"K"; updatePreview(); };
brightness.oninput = ()=>{
    document.getElementById("bv").innerText=brightness.value+"%"; updatePreview(); };

function presetRed()  { mode="rg";    r.value=255;g.value=0;  brightness.value=100;
    document.getElementById("rv").innerText="255";
    document.getElementById("gv").innerText="0";
    document.getElementById("bv").innerText="100%"; updatePreview(); }
function presetGreen(){ mode="rg";    r.value=0;  g.value=255;brightness.value=100;
    document.getElementById("rv").innerText="0";
    document.getElementById("gv").innerText="255";
    document.getElementById("bv").innerText="100%"; updatePreview(); }
function presetCold() { mode="white"; white.value=6000;brightness.value=100;
    document.getElementById("wv").innerText="6000K";
    document.getElementById("bv").innerText="100%"; updatePreview(); }

function applyColor() {
    let url = mode==="rg"
        ? `/apply?mode=rg&r=${r.value}&g=${g.value}&brightness=${brightness.value}`
        : `/apply?mode=white&temp=${white.value}&brightness=${brightness.value}`;
    fetch(url);
}

let lastCount = 0;
function levelClass(line) {
    if(line.includes(" ERROR "))   return "log-ERROR";
    if(line.includes(" WARNING ")) return "log-WARNING";
    if(line.includes(" DEBUG "))   return "log-DEBUG";
    return "log-INFO";
}
function loadLogs() {
    fetch("/logs").then(r=>r.json()).then(data=>{
        if(data.length===lastCount) return;
        lastCount = data.length;
        const box = document.getElementById("logbox");
        box.innerHTML = data.map(l=>
            `<span class="${levelClass(l)}">${l}</span>`
        ).join("\n");
        box.scrollTop = box.scrollHeight;
    });
}
setInterval(()=>{
    if(document.getElementById("logs").classList.contains("active")) loadLogs();
}, 1000);

updatePreview();
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def panel():
    return HTML

@app.get("/logs")
def get_logs():
    return JSONResponse(log_records)

@app.get("/apply")
def apply(mode: str, r: int = 0, g: int = 0,
          temp: int = 3000, brightness: int = 100):
    scale = max(0, min(100, brightness)) / 100
    if mode == "rg":
        send_color([int(r*scale), int(g*scale), 0, 0, 0])
        return {"status": "ok"}
    if mode == "white":
        cold_ratio = (temp - 3000) / 3000
        warm = int(255 * (1 - cold_ratio) * scale)
        cold = int(255 * cold_ratio * scale)
        send_color([0, 0, 0, warm, cold])
        return {"status": "ok"}
    return {"status": "error"}


# ===== Запуск =====
def start_server():
    config = uvicorn.Config(app, host=PC_IP, port=PC_PORT, log_level="warning")
    uvicorn.Server(config).run()

if __name__ == "__main__":
    threading.Thread(target=start_ble_loop, daemon=True).start()
    threading.Thread(target=start_server, daemon=True).start()

    import time; time.sleep(1)

    webview.create_window(
        "Lamp Control",
        f"http://{PC_IP}:{PC_PORT}",
        width=380,
        height=600,
        resizable=True,
    )
    webview.start()
