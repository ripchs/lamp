import asyncio
import threading
from bleak import BleakClient
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn

# ===== Настройки =====
ADDRESS = "41:42:AC:A2:76:C9"
CHAR_UUID = "0000fff4-0000-1000-8000-00805f9b34fb"
PC_IP = "0.0.0.0"
PC_PORT = 8000

current_color = [0, 0, 0, 0, 0]
previous_color = [255, 0, 0, 0, 0]

ble_client = None
ble_loop = None


# ===== BLE =====
async def ble_connect():
    global ble_client
    while True:
        try:
            ble_client = BleakClient(ADDRESS)
            await ble_client.connect()
            break
        except:
            await asyncio.sleep(2)


async def ble_write(value):
    global ble_client
    if not ble_client or not ble_client.is_connected:
        await ble_connect()

    try:
        await ble_client.write_gatt_char(CHAR_UUID, bytearray(value))
    except:
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

    asyncio.run_coroutine_threadsafe(
        ble_write(value),
        ble_loop
    )


# ===== FastAPI =====
app = FastAPI()


@app.get("/", response_class=HTMLResponse)
def panel():
    return """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Управление лампой</title>
<style>
body { background:#111; color:white; font-family:Arial; text-align:center; }
.slider { width:80%; }
button { padding:10px; margin:5px; border-radius:8px; border:none; }
.confirm { background:#4CAF50; color:white; }
.preset { background:#333; color:white; }
.preview {
    width:120px; height:120px; margin:15px auto;
    border-radius:12px; border:2px solid #444;
}
</style>
</head>
<body>

<h2>Lamp Control</h2>

<div class="preview" id="preview"></div>

<h3>Цвет</h3>
R <input type="range" min="0" max="255" value="255" id="r" class="slider"><br>
G <input type="range" min="0" max="255" value="0" id="g" class="slider"><br>

<h3>Температура белого</h3>
<input type="range" min="3000" max="6000" step="100" value="3000" id="white" class="slider">
<span id="whiteVal">3000K</span>

<h3>Яркость</h3>
<input type="range" min="0" max="100" value="100" id="brightness" class="slider">
<span id="brightVal">100%</span>

<h3>Пресеты</h3>
<button class="preset" onclick="presetRed()">Красный</button>
<button class="preset" onclick="presetGreen()">Зелёный</button>
<button class="preset" onclick="presetCold()">Белый</button>

<br><br>
<button class="confirm" onclick="confirm()">Подтвердить</button>

<script>

let mode = "rg";

const r = document.getElementById("r");
const g = document.getElementById("g");
const white = document.getElementById("white");
const brightness = document.getElementById("brightness");

function updatePreview(){
    let scale = brightness.value / 100;

    if(mode === "rg"){
        let rr = Math.floor(r.value * scale);
        let gg = Math.floor(g.value * scale);
        document.getElementById("preview").style.background =
            `rgb(${rr},${gg},0)`;
    } else {
        let intensity = Math.floor(255 * scale);
        document.getElementById("preview").style.background =
            `rgb(${intensity},${intensity},${intensity})`;
    }
}

[r,g].forEach(sl=>{
    sl.oninput = ()=>{
        mode = "rg";
        white.value = 3000;
        document.getElementById("whiteVal").innerText = white.value + "K";
        updatePreview();
    }
});

white.oninput = ()=>{
    mode = "white";
    r.value = 0;
    g.value = 0;
    document.getElementById("whiteVal").innerText = white.value + "K";
    updatePreview();
};

brightness.oninput = ()=>{
    document.getElementById("brightVal").innerText =
        brightness.value + "%";
    updatePreview();
};

function presetRed(){
    mode="rg";
    r.value=255; g.value=0;
    brightness.value=100;
    updatePreview();
}

function presetGreen(){
    mode="rg";
    r.value=0; g.value=255;
    brightness.value=100;
    updatePreview();
}

function presetCold(){
    mode="white";
    white.value=6000;
    brightness.value=100;
    document.getElementById("whiteVal").innerText="6000K";
    updatePreview();
}

function confirm(){
    if(mode==="rg"){
        fetch(`/apply?mode=rg&r=${r.value}&g=${g.value}&brightness=${brightness.value}`);
    } else {
        fetch(`/apply?mode=white&temp=${white.value}&brightness=${brightness.value}`);
    }
}

updatePreview();

</script>

</body>
</html>
"""


@app.get("/apply")
def apply(mode: str, r: int = 0, g: int = 0,
          temp: int = 3000, brightness: int = 100):

    scale = max(0, min(100, brightness)) / 100

    if mode == "rg":
        send_color([
            int(r * scale),
            int(g * scale),
            0,
            0,
            0
        ])
        return {"status": "ok"}

    if mode == "white":
        cold_ratio = (temp - 3000) / 3000
        warm = int(255 * (1 - cold_ratio) * scale)
        cold = int(255 * cold_ratio * scale)
        send_color([0, 0, 0, warm, cold])
        return {"status": "ok"}

    return {"status": "error"}


if __name__ == "__main__":
    threading.Thread(target=start_ble_loop, daemon=True).start()
    uvicorn.run(app, host=PC_IP, port=PC_PORT)
