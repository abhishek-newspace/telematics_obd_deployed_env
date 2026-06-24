# Serial (USB ↔ Motor Drive) Communication — Full Analysis

## Project: `MX_ES_DriverCan_TV4_01F_WD`  
**Language:** C# · **Framework:** .NET WinForms  
**Physical Layer:** USB-to-Serial (RS-485 / RS-232) via `System.IO.Ports.SerialPort`

---

## 1. Key Source Files

| File | Role |
|------|------|
| [Form1.cs](file:///c:/Users/rohit/Personal/Newspace/motor/MX_ES_DriverCan_TV4_01_WD/MX_ES_DriverCan_TV4_01F_WD/Form1.cs) | **Main hub** — serial port config, open/close, RX interrupt handler, all TX packet builders, CRC, firmware-upgrade thread |
| [global.cs](file:///c:/Users/rohit/Personal/Newspace/motor/MX_ES_DriverCan_TV4_01_WD/MX_ES_DriverCan_TV4_01F_WD/global.cs) | Shared globals: `display_Data[200]`, `read_ID[4]`, timing flags, firmware-upgrade state |
| `user` class (bottom of Form1.cs, lines 4146–4320) | Shared static buffers: `send_buf[700]`, `send_gloBuf[2000]`, `rece_slow[]`, `auchCRCHi[]`, `auchCRCLo[]`, all CRC lookup tables |
| [windows3.cs](file:///c:/Users/rohit/Personal/Newspace/motor/MX_ES_DriverCan_TV4_01_WD/MX_ES_DriverCan_TV4_01F_WD/windows3.cs) | Parameter/tuning UI — triggers send actions via `global.*_Status` flags |
| [windows4.cs](file:///c:/Users/rohit/Personal/Newspace/motor/MX_ES_DriverCan_TV4_01_WD/MX_ES_DriverCan_TV4_01F_WD/windows4.cs) | Firmware upgrade UI — progress bar, log text box |
| [windows2.cs](file:///c:/Users/rohit/Personal/Newspace/motor/MX_ES_DriverCan_TV4_01_WD/MX_ES_DriverCan_TV4_01F_WD/windows2.cs) | Secondary window (parameter display) |

---

## 2. Physical / Transport Layer

```
PC (app) ──USB──► USB-to-Serial adapter ──RS-485/RS-232──► Motor Drive Controller
```

- **Class used:** `System.IO.Ports.SerialPort`  
- **Default baud rate:** `115200` (parameter mode) · `38400` (alternate / w2 mode)  
- **Data bits:** 8 · **Parity:** None · **Stop bits:** 1  
- **Port selection:** dynamically enumerated via `SerialPort.GetPortNames()`, sorted by name length then alphabetically  

### Opening the Port
```csharp
// From serial_port_open() — Form1.cs:193
serial.PortName    = cbo_port_name.Text;
serial.BaudRate    = int.Parse(cbo_port_baud_rate.Text);   // 115200
serial.Parity      = Parity.None;
serial.DataBits    = 8;
serial.StopBits    = StopBits.One;
serial.Open();
```

---

## 3. Protocol Overview

There are **two distinct protocol layers** used simultaneously by the same serial port, selected by `global.winMark`:

| `winMark` | Protocol | Used For |
|-----------|----------|----------|
| `3` | **Custom frame** (start code `0xF1`, CRC-16 lookup table) | Parameter read/write, motor control |
| `4` | **Modbus-RTU-like frame** (CRC computed inline) | Firmware upgrade binary transfer |

---

## 4. Custom Protocol (winMark == 3)

### 4.1 TX Packet Structure

All command packets are **8 bytes** (except the 200-byte save and 48-byte load-test commands):

```
Byte[0]  Start Code    = 0xF1   (fixed — identifies the PC as sender)
Byte[1]  Function Code           (see table below)
Byte[2]  Frame Length            (total bytes in this frame, e.g. 0x08 = 8)
Byte[3]  Reserved      = 0x00
Byte[4]  Reserved      = 0x00
Byte[5]  Reserved      = 0x00
Byte[6]  CRC16 High Byte
Byte[7]  CRC16 Low Byte
```

For the **parameter save (Fn=0x92)** the payload grows to 200 bytes:
```
Byte[0]  = 0xF1  (start)
Byte[1]  = 0x92  (function: save)
Byte[2]  = 200   (length)
Byte[3..7]   = reserved
Byte[8..197] = parameter payload  (see §6 Byte Map)
Byte[198] = CRC16 High
Byte[199] = CRC16 Low
```

### 4.2 Function Code Table

| Fn Code | Name | Direction | Payload Size |
|---------|------|-----------|--------------|
| `0x89` | Drive Reset / Firmware Update Command | TX only | 8 bytes |
| `0x90` | Read Drive Version | TX→RX | 8 bytes TX / 8 bytes RX |
| `0x91` | Read Drive Parameters (live data) | TX→RX | 8 bytes TX / 200 bytes RX |
| `0x92` | Save Parameters (write all config) | TX→RX | 200 bytes TX / 8 bytes RX |
| `0x93` | Motor ID Identification | TX→RX | 8 bytes |
| `0x94` | Data Update | TX→RX | 8 bytes |
| `0x95` | Hall ID Identification | TX→RX | 8 bytes |
| `0x96` | Stop ID | TX→RX | 8 bytes |
| `0x97` | Load Test — Motor1 ON + Motor2 ON | TX→RX | 48 bytes |
| `0x98` | Load Test — Motor1 OFF + Motor2 ON | TX→RX | 48 bytes |
| `0x99` | Load Test — Motor1 ON + Motor2 OFF | TX→RX | 48 bytes |

### 4.3 RX Packet Structure (Custom Protocol)

```
Byte[0]  = 0xF1  (device start code — validates the sender is the drive)
Byte[1]  = Function Code (0x89–0x96)
Byte[2..N-3] = payload data
Byte[N-2] = CRC16 High
Byte[N-1] = CRC16 Low
```

The expected receive length is set per command in `user.uart_ReceByteLength`.  
After receiving, the CRC of bytes `[0 .. N-3]` is verified with `CRC16_R()`.

---

## 5. Firmware Upgrade Protocol (winMark == 4)

Used only from `windows4` (firmware flash tab). This is a **Modbus-RTU style** packet.

### 5.1 TX Packet for Upgrade (Function `0x08`)

```
Byte[0]   Device Address    = 0x00  (broadcast)
Byte[1]   Function Code     = 0x08
Byte[2]   Package No. High  (current packet number, big-endian)
Byte[3]   Package No. Low
Byte[4]   Byte Count High   (number of data bytes in this packet)
Byte[5]   Byte Count Low
Byte[6]   Remaining Pkg Hi  (remaining package count)
Byte[7]   Remaining Pkg Lo
Byte[8]   Reserved Hi       = 0x00
Byte[9]   Reserved Lo       = 0x00
Byte[10..10+N-1]  Data bytes (up to 512 bytes per packet)
Byte[-2]  CRC16 Low  (Modbus byte order: LOW first)
Byte[-1]  CRC16 High
```

> **Note:** CRC bytes are in **little-endian** order here (low byte first), unlike the custom protocol which is big-endian.

### 5.2 Upgrade Handshake Sequence

```
Step 0a:  PC sends  [0x00, 0x08, 0x00, 0x00, 0x00, 0x02, pkgCount_hi, pkgCount_lo, 0x00, 0x00, 0xAA, 0xAA, CRC_lo, CRC_hi]
          (data payload = 0xAA 0xAA → "handshake request")
          Wait up to 30 s for ACK

Step 0b:  PC sends  [0x00, 0x08, 0x00, 0x00, 0x00, 0x02, pkgCount_hi, pkgCount_lo, 0x00, 0x00, 0xAA, 0x01, CRC_lo, CRC_hi]
          (data payload = 0xAA 0x01 → "begin erase")
          Wait up to 15 s for ACK (flash erase time)

Steps 1..N: PC sends 512-byte data chunks, waits up to 5 s per chunk for ACK
```

### 5.3 RX Packet for Upgrade (8 bytes)

```
Byte[0]   Device Address
Byte[1]   = 0x08  (echoed function code)
Byte[2]   Package No. High  (echoed)
Byte[3]   Package No. Low
Byte[4]   (reserved)
Byte[5]   Status Code
Byte[6]   CRC16 Low
Byte[7]   CRC16 High
```

### 5.4 Status Codes in ACK

| `Byte[5]` | Meaning |
|-----------|---------|
| `0xF1` | ✅ Success — packet received and saved |
| `0xFA` | ❌ Device receive error |
| `0xF0` | ❌ Data received OK but save failed |
| `0xF2` | ❌ Firmware size exceeds device storage |
| `0xF3` | ❌ Packet format error |
| `0xF4` | ❌ Packet out of sequence |
| `0xF5` | ❌ Flash erase failed |

---

## 6. Byte Packing — TX (PC → Drive)

### 6.1 Simple 8-byte Commands (`readDrivePara`, `readDriveVersion`, etc.)

```csharp
// Form1.cs:2478  readDrivePara()
send_buf[0] = 0xF1;          // start code
send_buf[1] = 0x91;          // function: read params
send_buf[2] = 8;             // frame length
send_buf[3..5] = 0x00;       // reserved
// CRC over bytes [0..5]:
temp = CRC16_S(6);
send_buf[6] = (byte)(temp >> 8);   // CRC high
send_buf[7] = (byte)(temp & 0xFF); // CRC low
```

### 6.2 200-byte Parameter Save (`write_w2_saveParameterInit`)

Each field is packed **big-endian** (MSB first). Floats use a **byte-reversed IEEE 754** encoding via `float_byte_B()`.

```csharp
// float_byte_B() — Form1.cs:2236
// Converts float → 4 bytes stored big-endian (MSB first)
byte[] svs = BitConverter.GetBytes(f);  // little-endian on x86
FtoB[0] = svs[3];  // MSB
FtoB[1] = svs[2];
FtoB[2] = svs[1];
FtoB[3] = svs[0];  // LSB
```

**Complete parameter map (byte offset in send_buf):**

| Offset | Size | Parameter | Encoding |
|--------|------|-----------|----------|
| 0 | 1 | Start Code (`0xF1`) | `byte` |
| 1 | 1 | Function Code (`0x92`) | `byte` |
| 2 | 1 | Frame Length (200) | `byte` |
| 3–7 | 5 | Reserved | `0x00` |
| 8 | 1 | Control Type (0=Analog, 1=RS485, 2=CAN, 3=Remote, 4=Rocker) | `uint8` |
| 9 | 1 | RS485 Address | `uint8` |
| 10–13 | 4 | RS485 Baud Rate | `uint32` big-endian |
| 14–17 | 4 | CAN Transmit ID | `uint32` big-endian, hex input |
| 18–21 | 4 | CAN Receive ID | `uint32` big-endian, hex input |
| 22 | 1 | CAN Baud (0=100K, 3=250K, 4=500K) | `uint8` |
| 23 | 1 | CAN Frame Type (0=Standard, 1=Extended) | `uint8` |
| 24 | 1 | M1 Motor Mode (0=Torque, 1=Speed, 2=Position) | `uint8` |
| 25 | 1 | M1 Direction (0=Forward, 1=Reverse) | `uint8` |
| 26 | 1 | M2 Motor Mode | `uint8` |
| 27 | 1 | M2 Direction | `uint8` |
| 28–29 | 2 | Pole Pairs | `uint16` big-endian |
| 30–31 | 2 | Acceleration % | `uint16` big-endian |
| 32–33 | 2 | Deceleration % | `uint16` big-endian |
| 34–35 | 2 | Kp Speed | `uint16` big-endian |
| 36–37 | 2 | Ki Speed | `uint16` big-endian |
| 38 | 1 | Auto-Hold enable | `uint8` (0/1) |
| 39 | 1 | Encoder A/B Swap | `uint8` (0/1) |
| 40 | 1 | Sensor Types (M1 high nibble, M2 low nibble) | packed nibble |
| 41 | 1 | BMQ Pole Pairs | `uint8` |
| 42–43 | 2 | Rated Speed | `uint16` big-endian |
| 44 | 1 | Reserved / State Mark | `uint8` |
| 45 | 1 | Brake Enable (bit 0) | bitfield |
| 46–53 | 8 | Reserved | `0x00` |
| 54–55 | 2 | Over-current threshold (A) | `uint16` big-endian |
| 56–57 | 2 | Over-current time (ms) | `uint16` big-endian |
| 58–59 | 2 | Max current time | `uint16` big-endian |
| 60–61 | 2 | Send interval (ms) | `uint16` big-endian |
| 62–69 | 8 | (Reserved / fault flags position) | — |
| 70–73 | 4 | Max Bus Current (A) | `float32` big-endian |
| 74–77 | 4 | Max Phase Current (A) | `float32` big-endian |
| 78–81 | 4 | Max Voltage (V) | `float32` big-endian |
| 82–85 | 4 | Min Voltage (V) | `float32` big-endian |
| 86–89 | 4 | Kp (Idq current loop) | `float32` big-endian |
| 90–93 | 4 | Ki (Idq current loop) | `float32` big-endian |
| 94–97 | 4 | Pick-up Voltage | `float32` big-endian |
| 98–101 | 4 | Hold Voltage | `float32` big-endian |
| 102–105 | 4 | Brake Delay (s) | `float32` big-endian |
| 106–109 | 4 | Drive Down-time (s) | `float32` big-endian |
| 110–113 | 4 | Rs_Current | `float32` big-endian |
| 114–117 | 4 | Ls_Current | `float32` big-endian |
| 118–121 | 4 | R/L (Hz) | `float32` big-endian |
| 122–125 | 4 | Flux (V/Hz) | `float32` big-endian |
| 126–129 | 4 | Rs (Ohm) | `float32` big-endian |
| 130–133 | 4 | Lsq (H) | `float32` big-endian |
| 134–137 | 4 | Lsd (H) | `float32` big-endian |
| 138–141 | 4 | Analog Limit Max CW (speed) | `float32` big-endian |
| 142–145 | 4 | Analog Limit Max CCW (speed) | `float32` big-endian |
| 146–149 | 4 | Brake Resistor Voltage | `float32` big-endian |
| 150–153 | 4 | SF Tim MaxI | `float32` big-endian |
| 154–197 | 44 | Reserved | `0x00` |
| 198 | 1 | CRC16 High | CRC over bytes [0..197] |
| 199 | 1 | CRC16 Low | |

---

## 7. Byte Unpacking — RX (Drive → PC)

Received bytes go into `global.display_Data[200]` via `serial_DataReceived()`, then `dis_Refresh()` decodes them. The RX map **mirrors** the TX map at the same byte offsets.

### Key Unpack Patterns

**1-byte integer:**
```csharp
I_c_s = global.display_Data[8];     // e.g. Control Type
```

**2-byte unsigned integer (big-endian):**
```csharp
I_c_s = global.display_Data[28];
I_c_s = (UInt16)((I_c_s << 8) | global.display_Data[29]);  // Pair (pole pairs)
```

**4-byte unsigned integer (big-endian):**
```csharp
U_c_s = global.display_Data[10];
U_c_s = (U_c_s << 8) | global.display_Data[11];
U_c_s = (U_c_s << 8) | global.display_Data[12];
U_c_s = (U_c_s << 8) | global.display_Data[13];  // RS485 Baud Rate
```

**4-byte float (big-endian IEEE 754, reversed for BitConverter):**
```csharp
// byte_order() — Form1.cs:2227
// Reverses 4 bytes because BitConverter expects little-endian
order_buf[0] = global.display_Data[cont + 3];  // LSB
order_buf[1] = global.display_Data[cont + 2];
order_buf[2] = global.display_Data[cont + 1];
order_buf[3] = global.display_Data[cont + 0];  // MSB

// Then:
float value = BitConverter.ToSingle(order_buf, 0);
```

**Packed nibble (sensor type byte[40]):**
```csharp
// M1 sensor = high nibble
I_c_s = (UInt16)((global.display_Data[40] >> 4) & 0x0F);
// M2 sensor = low nibble
I_c_s = (UInt16)(global.display_Data[40] & 0x0F);
```

**8-byte fault bitmask (uint64):**
```csharp
U64 = global.display_Data[62];
U64 = (U64 << 8) | global.display_Data[63];
// ... (continued for bytes 64–69)
if ((U64 & 0x0000000000000001) != 0) /* M1/M2 Phase Sensor fault */
if ((U64 & 0x0000000000000010) != 0) /* Over-current */
// ... (30+ fault bits)
```

### Complete RX Display Map

| Offset | Size | Parameter | Display |
|--------|------|-----------|---------|
| 8 | 1 | Control Type | Radio buttons |
| 9 | 1 | RS485 Address | textBox1 |
| 10–13 | 4 | RS485 Baud | comboBox1 |
| 14–17 | 4 | CAN TX ID | textBox11 |
| 18–21 | 4 | CAN RX ID | textBox2 |
| 22 | 1 | CAN Baud | comboBox2 |
| 23 | 1 | CAN Frame Type | radioButton12/13 |
| 24 | 1 | M1 Mode | radioButton1/2/10 |
| 25 | 1 | M1 Direction | radioButton19/20 |
| 26 | 1 | M2 Mode | radioButton6/7/11 |
| 27 | 1 | M2 Direction | radioButton4/5 |
| 28–29 | 2 | Pole Pairs | textBox8 |
| 30–31 | 2 | Acceleration | trackBar1 |
| 32–33 | 2 | Deceleration | trackBar2 |
| 34–35 | 2 | Kp Speed | textBox17 |
| 36–37 | 2 | Ki Speed | textBox21 |
| 38 | 1 | Auto-Hold | checkBox3 |
| 39 | 1 | Encoder Swap | checkBox1 |
| 40 | 1 | Sensor Types (nibbles) | radioButton14–21 |
| 41 | 1 | BMQ Pairs | textBox22 |
| 42–43 | 2 | Rated Speed | textBox24 |
| 44 | 1 | Brake Enable state | label64 |
| 45 | 1 | Brake (bit 0) | checkBox2 |
| 54–55 | 2 | OverCur_I | textBox30 |
| 56–57 | 2 | OverCur_Tim | textBox31 |
| 58–59 | 2 | Tim_maxI | textBox32 |
| 60–61 | 2 | Send Interval | textBox28 |
| 62–69 | 8 | Fault Bitmask | label67 |
| 70–73 | 4 | VdcBus_kV | label28 |
| 74–77 | 4 | Bus Current | label29 |
| 78–81 | 4 | Throttle Voltage | label53 |
| 82–85 | 4 | Controller Temp | label49 |
| 86–89 | 4 | M1/M2 Speed (float, RPM) | label17 |
| 90–93 | 4 | M1/M2 Current (float, A) | label19 |
| 94–97 | 4 | M1/M2 Temperature | label54 |
| 98–101 | 4 | M2/M1 Speed | label33 |
| 102–105 | 4 | M2/M1 Current | label36 |
| 106–109 | 4 | M2/M1 Temperature | label56 |
| 110–113 | 4 | Max Bus Current | textBox45 |
| 114–117 | 4 | Max Phase Current | textBox39 |
| 118–121 | 4 | Max Voltage | textBox40 |
| 122–125 | 4 | Min Voltage | textBox46 |
| 126–129 | 4 | Kp_Idq | textBox10 |
| 130–133 | 4 | Ki_Idq | textBox16 |
| 134–137 | 4 | Pick-up Voltage | textBox25 |
| 138–141 | 4 | Hold Voltage | textBox26 |
| 142–145 | 4 | Brake Delay | textBox27 |
| 146–149 | 4 | Drive Downtime | textBox29 |
| 150–153 | 4 | Rs_Current | textBox18 |
| 154–157 | 4 | Ls_Current | textBox19 |
| 158–161 | 4 | R/L Hz | textBox20 |
| 162–165 | 4 | Flux_VpHz | textBox9 |
| 166–169 | 4 | Rs_Ohm | textBox5 |
| 170–173 | 4 | Lsq_H | textBox7 |
| 174–177 | 4 | Lsd_H | textBox6 |
| 178–181 | 4 | Analog LimitMax CW | textBox12 |
| 182–185 | 4 | Analog LimitMax CCW | textBox13 |
| 186–189 | 4 | volBRres (brake resistor V) | textBox23 |
| 190–193 | 4 | SF_Tim_maxI | textBox33 |

> **Motor swap note:** When `global.motorSwapMark == 1` (some 24-tube / 36-tube PCBs), bytes [24]↔[26] (mode) and [25]↔[27] (direction) are **swapped on both TX and RX** to correct the physical motor mapping.

---

## 8. CRC-16 Algorithm

Two CRC functions are used — both are **CRC-16/Modbus** using a pre-computed lookup table (`auchCRCHi[256]` + `auchCRCLo[256]` stored in `user` class):

```csharp
// CRC16_S — over send_buf[] (TX)   Form1.cs:3960
// CRC16_R — over rece_slow[] (RX)  Form1.cs:3982

uint CRC16_S(uint dataLen)
{
    byte uchCRCHi = 0xFF;   // init both bytes to 0xFF
    byte uchCRCLo = 0xFF;
    byte idx = 0;
    while (dataLen-- > 0)
    {
        int uIndex = uchCRCHi ^ send_buf[idx++];
        uchCRCHi = uchCRCLo ^ auchCRCHi[uIndex];
        uchCRCLo = auchCRCLo[uIndex];
    }
    return (uint)((uchCRCHi << 8) | uchCRCLo);
}
```

- Result is returned as `(High << 8) | Low`
- Custom protocol stores: `[6]=High, [7]=Low` (big-endian)
- Modbus upgrade protocol (via `calc_modbus_crc`) stores: `[n]=Low, [n+1]=High` (little-endian)

The firmware upgrade path uses a **different** inline Modbus CRC:
```csharp
// calc_modbus_crc() — Form1.cs:1010
// XOR-shift algorithm (no lookup table), polynomial 0xA001
private byte[] calc_modbus_crc(byte[] buffer, uint length)
{
    UInt16 crc = 0xFFFF;
    for (int i = 0; i < length; i++) {
        crc ^= buffer[i];
        for (int j = 0; j < 8; j++) {
            if ((crc & 1) != 0) { crc >>= 1; crc ^= 0xA001; }
            else crc >>= 1;
        }
    }
    return BitConverter.GetBytes(crc);  // returns [Low, High]
}
```

---

## 9. Threading Model

```
Main Thread (UI)
│
├── 25ms Timer (tixA) ─────► TimedEvent_InterruptB()
│                               ├── if winMark==3 → data_send_start()  (spawns data_thread)
│                               └── if winMark==4 → file_send_start()  (spawns file_thread)
│
├── data_thread ──────────► Send_UpgradeData()
│                               Builds TX frame → uart_sendFun1() → serial.Write()
│
├── file_thread ──────────► Send_UpgradeFile()
│                               Streams .dat file → send_byte_buffer() → serial.Write()
│
└── serial.DataReceived ──► serial_DataReceived()  (RX interrupt)
                                Accumulates bytes in Rev_Byte_buffer (List<byte>)
                                Validates start code + function code
                                Copies complete frame to user.rece_slow[]
                                Verifies CRC → updates display_Data[] → BeginInvoke(InitViewAB)
```

> **Important:** `Control.CheckForIllegalCrossThreadCalls = false` is set at startup, allowing direct UI updates from background threads (line 128 Form1.cs).

---

## 10. RX Frame Parsing State Machine

```
serial_DataReceived()  [Form1.cs:775]
│
├── [winMark==3]  Custom Protocol
│     ├── Read all bytes from serial → append to Rev_Byte_buffer
│     ├── Loop while buffer.Count > 1:
│     │    ├── buffer[0] == 0xF1?  → check buffer[1] in [0x89..0x96]
│     │    │    ├── buffer.Count < uart_ReceByteLength? → BREAK (wait for more)
│     │    │    ├── Copy uart_ReceByteLength bytes to rece_slow[]
│     │    │    └── Clear buffer, set r_end=1
│     │    └── else: RemoveAt(0)  ← shift window (sync search)
│     │
│     └── if r_end==1:
│          ├── CRC16_R(length-2) == rece_slow[n-2..n-1]?
│          ├── Parse receFunctionCode from rece_slow[1]
│          ├── Copy to display_Data[0..199]
│          └── BeginInvoke(InitViewAB) → dis_Refresh()
│
└── [winMark==4]  Modbus-RTU (upgrade)
      ├── Read all bytes → append to Rev_Byte_buffer  
      ├── Loop while buffer.Count > 1:
      │    ├── buffer[1] in {0x08, 0x09, 0x06}?
      │    │    ├── buffer.Count < 8? → BREAK
      │    │    ├── Copy 8 bytes to ReceiveBytes[]
      │    │    └── calc_modbus_crc(ReceiveBytes, 8) == [0,0]?
      │    │         ├── YES → RevFlag = true  (ACK to file_thread)
      │    │         └── NO  → continue (discard)
      │    └── else: RemoveAt(0)
      └── file_thread polls RevFlag in a tight loop
```

---

## 11. Timing & Polling

| Timer/Delay | Value | Purpose |
|-------------|-------|---------|
| `tixA.Interval` | 25 ms | Main poll timer |
| `loop_count >= 12` | ~300 ms | Normal parameter read interval |
| `loop_count >= 4` | ~100 ms | Drive reset send interval |
| `Thread.Sleep(100)` | 100 ms | Handshake retry interval |
| `Thread.Sleep(50)` | 50 ms | Post-packet gap |
| `RevTimeOut = 30` | 30 s | Handshake timeout |
| `RevTimeOut = 15` | 15 s | Flash erase timeout |
| `RevTimeOut = 5` | 5 s | Data packet timeout |
| `PerPackageByte` | 512 bytes | Firmware upgrade chunk size |
