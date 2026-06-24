# UART Frame Packing / Unpacking — Byte-Level Walkthrough

> **Source files:** [Form1.cs](file:///c:/Users/rohit/Personal/Newspace/motor/MX_ES_DriverCan_TV4_01_WD/MX_ES_DriverCan_TV4_01F_WD/Form1.cs) · [global.cs](file:///c:/Users/rohit/Personal/Newspace/motor/MX_ES_DriverCan_TV4_01_WD/MX_ES_DriverCan_TV4_01F_WD/global.cs)

---

## Overview — Two Protocol Modes on the Same UART Line

```
┌─────────────────────────────────────────────────────────────────────┐
│                  Single Serial Port (COMx, 8N1)                      │
│                                                                       │
│  winMark = 3  ──►  Custom Frame  (0xF1 start, lookup-table CRC-16)  │
│  winMark = 4  ──►  Modbus-RTU Frame  (0x08 Fn, XOR-shift CRC-16)   │
└─────────────────────────────────────────────────────────────────────┘
```

Both share the **same `SerialPort` object** (`serial`) and the **same `DataReceived` interrupt handler** (`serial_DataReceived`). The mode switch happens via `global.winMark`.

---

## PART A — Custom Protocol (winMark = 3)

### A.1 UART Physical Layer Settings

```
BaudRate  : 38400  (set by serial_checkPort_w2, Form1.cs:226)
DataBits  : 8
Parity    : None
StopBits  : 1
Flow Ctrl : None
```

So each byte on the wire is:  `[START(1)] [D0..D7(8)] [STOP(1)]` = **10 bit-times @ 38400** ≈ 26 µs/byte.

---

### A.2 TX Frame — How a Command is Packed (step by step)

#### Step 1 — Clear the send buffer
```csharp
// send_clear()  Form1.cs:2201
for (i = 0; i < 700; i++)
    user.send_buf[i] = 0;
```
`user.send_buf[]` is the staging area (700 bytes, static). Every field is placed here first.

#### Step 2 — Fill the header fields (example: Read Parameters Fn=0x91)
```csharp
// readDrivePara()  Form1.cs:2478
user.send_buf[0] = 0xF1;   // Start Code — always 0xF1, identifies PC sender
user.send_buf[1] = 0x91;   // Function Code
user.send_buf[2] = 0x08;   // Frame length (total bytes = 8)
user.send_buf[3] = 0x00;   // Reserved
user.send_buf[4] = 0x00;   // Reserved
user.send_buf[5] = 0x00;   // Reserved
```

#### Step 3 — Compute CRC-16 over bytes [0..5]
```csharp
// CRC16_S(6)  Form1.cs:3960
// Lookup-table CRC-16/Modbus, seed = 0xFFFF
uint temp = CRC16_S(6) & 0x0000ffff;
user.send_buf[6] = (byte)(temp >> 8);    // CRC HIGH byte first
user.send_buf[7] = (byte)(temp & 0xFF);  // CRC LOW  byte second
```

#### Step 4 — Copy to the live send buffer
```csharp
// conver_sendParameter(len)  Form1.cs:2218
for (i = 0; i < len; i++)
    user.send_gloBuf[i] = user.send_buf[i];
```

#### Step 5 — Write to the serial port
```csharp
// uart_sendFun1(len)  Form1.cs:2043
serial.Write(user.send_gloBuf, 0, len);
```

---

### A.3 Complete TX Frame Wire Layout (8-byte command)

```
Offset  Byte  Description
──────  ────  ──────────────────────────────────────────
 [0]    0xF1  Start Code (PC identifier)
 [1]    0xNN  Function Code  (see table below)
 [2]    0xLL  Frame Length   (total bytes in frame)
 [3]    0x00  Reserved
 [4]    0x00  Reserved
 [5]    0x00  Reserved
 [6]    0xHH  CRC-16 HIGH byte   ← computed over [0..5]
 [7]    0xLL  CRC-16 LOW  byte
```

> **Byte order rule:** All multi-byte integers in the custom protocol are **big-endian** (MSB first).  
> CRC is stored **high byte first** at the end.

#### Function Code Table
```
Fn    Name                    TX len   RX len
0x89  Drive Reset (prep FW)     8        8
0x90  Read Version              8        8
0x91  Read Parameters           8       200
0x92  Save Parameters         200        8
0x93  Motor ID                  8        8
0x94  Data Update               8        8
0x95  Hall ID                   8        8
0x96  Stop ID                   8        8
0x97  M1-ON  M2-ON  (run)      48      200
0x98  M1-OFF M2-ON  (run)      48      200
0x99  M1-ON  M2-OFF (run)      48      200
```

---

### A.4 Real Worked Example — "Read Parameters" Frame

```
Bytes to send:  F1 91 08 00 00 00 ?? ??
                                    ┌─┘└─┐
                      CRC over [F1 91 08 00 00 00] = ?
```

**CRC-16 Lookup computation (CRC16_S, seed=0xFFFF):**
```
init:  Hi=0xFF  Lo=0xFF

byte 0: 0xF1
  idx = Hi ^ 0xF1 = 0xFF ^ 0xF1 = 0x0E
  Hi  = Lo ^ auchCRCHi[0x0E] = 0xFF ^ 0x81 = 0x7E
  Lo  = auchCRCLo[0x0E]      = 0xCC

byte 1: 0x91
  idx = Hi ^ 0x91 = 0x7E ^ 0x91 = 0xEF
  Hi  = Lo ^ auchCRCHi[0xEF] = 0xCC ^ 0x40 = 0x8C
  Lo  = auchCRCLo[0xEF]      = 0x60

byte 2: 0x08
  idx = Hi ^ 0x08 = 0x8C ^ 0x08 = 0x84
  Hi  = Lo ^ auchCRCHi[0x84] = 0x60 ^ 0x00 = 0x60
  Lo  = auchCRCLo[0x84]      = 0xFC

byte 3: 0x00
  idx = Hi ^ 0x00 = 0x60 ^ 0x00 = 0x60
  Hi  = Lo ^ auchCRCHi[0x60] = 0xFC ^ 0x01 = 0xFD
  Lo  = auchCRCLo[0x60]      = 0xF0

byte 4: 0x00
  idx = 0xFD ^ 0x00 = 0xFD
  Hi  = 0xF0 ^ auchCRCHi[0xFD] = 0xF0 ^ 0x40 = 0xB0
  Lo  = auchCRCLo[0xFD]        = 0x41

byte 5: 0x00
  idx = 0xB0 ^ 0x00 = 0xB0
  Hi  = 0x41 ^ auchCRCHi[0xB0] = 0x41 ^ 0x00 = 0x41
  Lo  = auchCRCLo[0xB0]        = 0xB0

Final CRC:  Hi=0x41  Lo=0xB0
```

**Wire bytes (hex):**
```
F1  91  08  00  00  00  41  B0
```

---

### A.5 RX Frame — How a Response is Unpacked

#### Step 1 — Interrupt fires, all available bytes read at once
```csharp
// serial_DataReceived()  Form1.cs:775
int byteNum = serial.BytesToRead;
byte[] x_rece = new byte[byteNum];
serial.Read(x_rece, 0, byteNum);          // reads all waiting bytes
Rev_Byte_buffer.AddRange(x_rece);         // append to sliding window
```

#### Step 2 — Sliding window sync search
```csharp
while (Rev_Byte_buffer.Count > 1)
{
    if (Rev_Byte_buffer[0] == 0xF1)           // ① valid start code?
    {
        if (Rev_Byte_buffer[1] >= 0x89 &&
            Rev_Byte_buffer[1] <= 0x96)       // ② valid function code?
        {
            if (Rev_Byte_buffer.Count < user.uart_ReceByteLength)
                break;                         // ③ not enough bytes yet — wait

            // ④ complete frame arrived — copy it
            Rev_Byte_buffer.CopyTo(0, user.rece_slow, 0,
                                   user.uart_ReceByteLength);
            Rev_Byte_buffer.Clear();
            r_end = 1;
        }
        else
            Rev_Byte_buffer.RemoveAt(0);       // wrong fn code, shift by 1
    }
    else
        Rev_Byte_buffer.RemoveAt(0);           // not 0xF1, shift by 1
}
```

> The "shift by 1" on mismatch is the **byte-stuffing / sync recovery** mechanism — it re-aligns to the next 0xF1 boundary automatically.

#### Step 3 — CRC Verification
```csharp
if (r_end == 1)
{
    r_end = 0;
    // Compute CRC over rece_slow[0 .. len-3]
    uint ha = CRC16_R(user.uart_ReceByteLength - 2) & 0x0000ffff;

    // Extract received CRC from last 2 bytes (big-endian)
    uint hb = user.rece_slow[user.uart_ReceByteLength - 2];
    hb = (hb << 8) + user.rece_slow[user.uart_ReceByteLength - 1];

    if (ha == hb)  // CRC match → process frame
    {
        user.receFunctionCode = user.rece_slow[1];
        // copy to display_Data for UI
        for (i = 0; i < 200; i++)
            global.display_Data[i] = user.rece_slow[i];

        this.BeginInvoke(new MethodInvoker(InitViewAB));
    }
    // if CRC mismatch → frame silently discarded
}
```

#### Step 4 — Data Extraction (unpack each field from rece_slow[])

**1-byte field:**
```csharp
byte controlType = global.display_Data[8];
```

**2-byte unsigned integer (big-endian):**
```csharp
UInt16 polePairs = (UInt16)(global.display_Data[28] << 8
                           | global.display_Data[29]);
```

**4-byte unsigned integer (big-endian):**
```csharp
UInt32 rs485Baud = (UInt32)global.display_Data[10];
rs485Baud = (rs485Baud << 8) | global.display_Data[11];
rs485Baud = (rs485Baud << 8) | global.display_Data[12];
rs485Baud = (rs485Baud << 8) | global.display_Data[13];
```

**4-byte float (received big-endian, BitConverter needs little-endian):**
```csharp
// byte_order(offset)  Form1.cs:2227
// Reverses 4 bytes so BitConverter.ToSingle() sees them little-endian
order_buf[0] = global.display_Data[offset + 3];  // LSB → [0]
order_buf[1] = global.display_Data[offset + 2];
order_buf[2] = global.display_Data[offset + 1];
order_buf[3] = global.display_Data[offset + 0];  // MSB → [3]

float value = BitConverter.ToSingle(order_buf, 0);
```

**Packed nibble (sensor types in byte[40]):**
```csharp
UInt16 M1sensor = (UInt16)((global.display_Data[40] >> 4) & 0x0F); // high nibble
UInt16 M2sensor = (UInt16)( global.display_Data[40]       & 0x0F); // low  nibble
```

**64-bit fault bitmask (bytes 62–69, MSB first):**
```csharp
UInt64 faults = global.display_Data[62];
faults = (faults << 8) | global.display_Data[63];
faults = (faults << 8) | global.display_Data[64];
faults = (faults << 8) | global.display_Data[65];
faults = (faults << 8) | global.display_Data[66];
faults = (faults << 8) | global.display_Data[67];
faults = (faults << 8) | global.display_Data[68];
faults = (faults << 8) | global.display_Data[69];
```

---

### A.6 200-byte "Save Parameters" TX Frame — Full Wire Layout

```
[0]        0xF1    Start Code
[1]        0x92    Function Code: Save Parameters
[2]        0xC8    Frame Length = 200 (0xC8)
[3..7]     0x00    Reserved (5 bytes)
─── Configuration Fields ──────────────────────────────────────────────
[8]        uint8   Control Type   (0=Analog 1=RS485 2=CAN 3=Remote 4=Rocker)
[9]        uint8   RS485 Address
[10..13]   uint32  RS485 Baud Rate       ← big-endian
[14..17]   uint32  CAN TX ID (hex)       ← big-endian
[18..21]   uint32  CAN RX ID (hex)       ← big-endian
[22]       uint8   CAN Baud  (0=100K, 3=250K, 4=500K)
[23]       uint8   CAN Frame (0=Standard, 1=Extended)
[24]       uint8   M1 Mode   (0=Torque, 1=Speed, 2=Position)
[25]       uint8   M1 Dir    (0=Forward, 1=Reverse)
[26]       uint8   M2 Mode
[27]       uint8   M2 Dir
[28..29]   uint16  Pole Pairs            ← big-endian
[30..31]   uint16  Acceleration %        ← big-endian
[32..33]   uint16  Deceleration %        ← big-endian
[34..35]   uint16  Kp Speed              ← big-endian
[36..37]   uint16  Ki Speed              ← big-endian
[38]       uint8   Auto-Hold  (0/1)
[39]       uint8   Encoder Swap (0/1)
[40]       packed  Sensor Types  [M1:hi4] [M2:lo4]
[41]       uint8   BMQ Pole Pairs
[42..43]   uint16  Rated Speed           ← big-endian
[44]       uint8   Reserved (State Mark)
[45]       bitfield Brake bit0
[46..53]   uint8   Reserved (8 bytes)
[54..55]   uint16  OverCurrent threshold (A)
[56..57]   uint16  OverCurrent time (ms)
[58..59]   uint16  Max Current time
[60..61]   uint16  Send Interval (ms)
[62..69]   uint8   Reserved (8 bytes)
─── Float Fields (all IEEE 754, big-endian) ───────────────────────────
[70..73]   float32  Max Bus Current (A)
[74..77]   float32  Max Phase Current (A)
[78..81]   float32  Max Voltage (V)
[82..85]   float32  Min Voltage (V)
[86..89]   float32  Kp Idq
[90..93]   float32  Ki Idq
[94..97]   float32  Pick-up Voltage
[98..101]  float32  Hold Voltage
[102..105] float32  Brake Delay (s)
[106..109] float32  Drive Down-time (s)
[110..113] float32  Rs Current
[114..117] float32  Ls Current
[118..121] float32  R/L Hz
[122..125] float32  Flux VpHz
[126..129] float32  Rs Ohm
[130..133] float32  Lsq H
[134..137] float32  Lsd H
[138..141] float32  Analog Limit Max CW
[142..145] float32  Analog Limit Max CCW
[146..149] float32  Brake Resistor Voltage
[150..153] float32  SF Tim MaxI
[154..197] uint8   Reserved (44 bytes)
─── Checksum ──────────────────────────────────────────────────────────
[198]      uint8   CRC-16 HIGH    ← computed over [0..197]
[199]      uint8   CRC-16 LOW
```

**How a float32 gets packed (big-endian):**
```csharp
// float_byte_B(float f)  Form1.cs:2236
byte[] svs = BitConverter.GetBytes(f);   // x86 is little-endian: [LSB ... MSB]
FtoB[0] = svs[3];   // MSB → wire byte 0
FtoB[1] = svs[2];
FtoB[2] = svs[1];
FtoB[3] = svs[0];   // LSB → wire byte 3

user.send_buf[70] = FtoB[0];  // placed big-endian in frame
user.send_buf[71] = FtoB[1];
user.send_buf[72] = FtoB[2];
user.send_buf[73] = FtoB[3];
```

---

### A.7 Custom-Protocol CRC-16 Algorithm

Uses **pre-computed lookup tables** stored in `user.auchCRCHi[256]` and `user.auchCRCLo[256]` (Form1.cs lines 4263–4319).

```
Polynomial : 0x8005  (standard CRC-16/Modbus)
Seed       : 0xFFFF
Bit order  : LSB first (reflected)
Result     : HIGH byte stored first, then LOW byte
```

```csharp
uint CRC16_S(uint dataLen)           // TX version, reads user.send_buf[]
uint CRC16_R(int dataLen)            // RX version, reads user.rece_slow[]

// Core algorithm (same for both):
byte Hi = 0xFF, Lo = 0xFF;
for each byte b in data:
    int idx = Hi ^ b;
    Hi = Lo ^ auchCRCHi[idx];
    Lo = auchCRCLo[idx];
result = (Hi << 8) | Lo;             // returned as uint
```

**Storage in frame (TX):**
```csharp
send_buf[n-2] = (byte)(result >> 8);   // HIGH first
send_buf[n-1] = (byte)(result & 0xFF); // LOW  second
```

**Verification on RX:**
```csharp
uint computed = CRC16_R(frameLen - 2);
uint received = (rece_slow[frameLen-2] << 8) | rece_slow[frameLen-1];
if (computed == received) → accept frame
```

---

## PART B — Modbus-RTU Firmware Upgrade Protocol (winMark = 4)

### B.1 UART Physical Layer Settings
```
BaudRate  : 115200  (set by serial_checkPort_w4, Form1.cs:250)
DataBits  : 8
Parity    : None
StopBits  : 1
```

---

### B.2 TX Frame — How a Firmware Chunk is Packed

The function [`send_byte_buffer()`](file:///c:/Users/rohit/Personal/Newspace/motor/MX_ES_DriverCan_TV4_01_WD/MX_ES_DriverCan_TV4_01F_WD/Form1.cs#L947-L1002) builds the frame dynamically into a `List<byte>`:

```csharp
send_byte_buffer(
    byte DevNo,       // Device address (0x00 = broadcast)
    byte Fn,          // Function code (0x08 for upgrade)
    uint Address,     // ← Package number
    int  DataNum,     // ← Number of data bytes in this packet
    byte[] data,      // ← Actual firmware bytes
    int reserved1,    // ← Remaining package count
    int reserved2     // ← Always 0
);
```

#### Byte-by-byte frame construction in `send_byte_buffer()`:

```csharp
buffer.Add(DevNo);          // [0] Device address = 0x00
buffer.Add(Fn);             // [1] Function code  = 0x08

// Address (= package number) — big-endian from uint
tmp = BitConverter.GetBytes(Address);  // little-endian on x86
buffer.Add(tmp[1]);         // [2] Package No. HIGH
buffer.Add(tmp[0]);         // [3] Package No. LOW

// DataNum (= byte count) — big-endian from int
tmp = BitConverter.GetBytes(DataNum);
buffer.Add(tmp[1]);         // [4] Byte Count HIGH
buffer.Add(tmp[0]);         // [5] Byte Count LOW

// --- Only for Fn=0x08 (upgrade) ---
// reserved1 (= remaining packages) — big-endian
tmp = BitConverter.GetBytes(reserved1);
buffer.Add(tmp[1]);         // [6] Remaining Pkgs HIGH
buffer.Add(tmp[0]);         // [7] Remaining Pkgs LOW

// reserved2 (= always 0) — big-endian
tmp = BitConverter.GetBytes(reserved2);
buffer.Add(tmp[1]);         // [8] Reserved HIGH = 0x00
buffer.Add(tmp[0]);         // [9] Reserved LOW  = 0x00

buffer.AddRange(data);      // [10 .. 10+N-1]  Firmware data bytes

// length used for CRC = 10 + DataNum
length = 10 + (uint)DataNum;

// Compute CRC over [0 .. length-1]
check_crc = calc_modbus_crc(buffer.ToArray(), length);

// Append CRC — NOTE: LOW byte first, then HIGH (Modbus standard)
buffer.Add(check_crc[0]);   // [length]   CRC LOW
buffer.Add(check_crc[1]);   // [length+1] CRC HIGH
```

---

### B.3 Complete TX Wire Layout — Firmware Data Packet

```
Byte      Value      Description
────────  ─────────  ──────────────────────────────────────────────────
[0]       0x00       Device Address (broadcast)
[1]       0x08       Function Code (firmware upgrade)
[2]       Pkt_H      Package Number HIGH  ← big-endian
[3]       Pkt_L      Package Number LOW
[4]       Cnt_H      Data Byte Count HIGH ← big-endian (e.g. 0x02 / 0x02 / 0x02 0x00)
[5]       Cnt_L      Data Byte Count LOW
[6]       Rem_H      Remaining Packages HIGH ← big-endian
[7]       Rem_L      Remaining Packages LOW
[8]       0x00       Reserved HIGH
[9]       0x00       Reserved LOW
[10]      data[0]    Firmware byte 0
[11]      data[1]    Firmware byte 1
 ...       ...        ...
[10+N-1]  data[N-1]  Firmware byte N-1  (N = DataNum, max 512)
[10+N]    CRC_LO     CRC-16 LOW  byte ← REVERSED vs custom proto!
[10+N+1]  CRC_HI     CRC-16 HIGH byte
```

> **Critical endianness difference:**  
> Custom protocol → CRC stored as **HIGH then LOW**  
> Modbus upgrade  → CRC stored as **LOW then HIGH** (standard Modbus byte order)

---

### B.4 Handshake Frames (special case of Fn=0x08, package #0)

**Step 0a — Handshake Request:**
```
send_byte_buffer(0x00, 0x08, Address=0, DataNum=2,
                 data=[0xAA, 0xAA],
                 reserved1=TotalPackage, reserved2=0)
```
Wire bytes:
```
00  08  00 00  00 02  Rem_H Rem_L  00 00  AA AA  CRC_L CRC_H
│   │   │ │    │ │    └──┬──┘      │ │    └──┬──┘
│   │   PkgNo  ByteCnt  Remaining Rsv  Payload(handshake magic)
│   Fn
DevAddr
```

**Step 0b — Erase Request (after handshake ACK):**
```
data=[0xAA, 0x01]
```
Wire bytes:
```
00  08  00 00  00 02  Rem_H Rem_L  00 00  AA 01  CRC_L CRC_H
```

**Steps 1..N — Data Chunks:**
```
send_byte_buffer(0x00, 0x08, Address=packageNo, DataNum=512,
                 data=<512 bytes from .bin file>,
                 reserved1=remaining, reserved2=0)
```
Wire bytes (first data packet, 512 bytes):
```
00  08  00 01  02 00  Rem_H Rem_L  00 00
[firmware bytes 0..511]
CRC_L  CRC_H
Total = 2 + 512 + 2 = 526 bytes on wire
        ↑             ↑
      header        CRC
```

**Last packet (partial):**
```
DataNum = TotalSize - 512*(TotalPackage-1)   // may be < 512
```

---

### B.5 Modbus-RTU CRC-16 Algorithm (used for upgrade)

This is the **XOR-shift (bit-bang)** variant — no lookup tables:

```csharp
// calc_modbus_crc()  Form1.cs:1010
UInt16 crc = 0xFFFF;
for (int i = 0; i < length; i++)
{
    crc ^= buffer[i];              // XOR byte into CRC LSB
    for (int j = 0; j < 8; j++)
    {
        if ((crc & 0x0001) != 0)  // if LSB set
        {
            crc >>= 1;             // shift right
            crc ^= 0xA001;         // XOR with reflected poly 0x8005
        }
        else
            crc >>= 1;
    }
}
return BitConverter.GetBytes(crc); // [0]=LOW, [1]=HIGH
```

```
Polynomial : 0x8005 (reflected → 0xA001)
Seed       : 0xFFFF
Result     : [0]=LOW byte,  [1]=HIGH byte
Wire order : LOW first, then HIGH  (Modbus standard)
```

**Worked example — handshake packet CRC:**
```
Data: 00 08 00 00 00 02 Rem_H Rem_L 00 00 AA AA   (12 bytes)
(assuming TotalPackage=5, Rem_H=0x00, Rem_L=0x05)

Data: 00 08 00 00 00 02 00 05 00 00 AA AA

init crc = 0xFFFF

byte 0x00: crc = 0xFFFF ^ 0x00 = 0xFFFF → 8 shifts → 0x8408
byte 0x08: crc = 0x8408 ^ 0x08 = 0x8400 → 8 shifts → 0xC001
byte 0x00: crc = 0xC001 ^ 0x00           → 8 shifts → 0xE001  (approx)
... (continues for all 12 bytes)

Result CRC = e.g. 0x4321
Wire appended: 21 43   (LOW first then HIGH)
```

---

### B.6 RX Frame — How the ACK is Received (winMark=4)

#### Step 1 — Bytes arrive in DataReceived interrupt
```csharp
int byteNum = serial.BytesToRead;
byte[] buffer = new byte[byteNum];
serial.Read(buffer, 0, byteNum);
Rev_Byte_buffer.AddRange(buffer);
```

#### Step 2 — Search for valid frame start
```csharp
while (Rev_Byte_buffer.Count > 1)
{
    if (Rev_Byte_buffer[0] <= 0xFF)              // ① any device address
    {
        if (Rev_Byte_buffer[1] == 0x08 ||
            Rev_Byte_buffer[1] == 0x09 ||
            Rev_Byte_buffer[1] == 0x06)          // ② valid function codes
        {
            if (Rev_Byte_buffer.Count < 8)
                break;                            // ③ need 8 bytes minimum

            Rev_Byte_buffer.CopyTo(0, ReceiveBytes, 0, 8);  // ④ grab frame
            Rev_Byte_buffer.Clear();

            // ⑤ Verify CRC — check_buffer should be all zeros
            byte[] check = calc_modbus_crc(ReceiveBytes, 8);
            if (check[0] == 0 && check[1] == 0)
                RevFlag = true;                   // ✅ valid ACK!
            // else discard silently
        }
        else
            Rev_Byte_buffer.RemoveAt(0);          // wrong fn, slide window
    }
    else
        Rev_Byte_buffer.RemoveAt(0);
}
```

> **CRC verification trick:** The Modbus-RTU way to verify is to run CRC over **all 8 bytes including the CRC itself** — the result must be `0x0000`. That is exactly what `calc_modbus_crc(ReceiveBytes, 8)` does.

#### ACK Frame Wire Layout (8 bytes, Drive → PC)
```
[0]  Device Address  (echoed)
[1]  0x08            Function Code (echoed)
[2]  Pkt_H           Package Number HIGH (echoed)
[3]  Pkt_L           Package Number LOW  (echoed)
[4]  0x00            Reserved
[5]  Status          Result code (see below)
[6]  CRC_LO          CRC-16 LOW
[7]  CRC_HI          CRC-16 HIGH
```

#### ACK Status Codes (ReceiveBytes[5])
```
0xF1  ✅  Packet received and saved successfully
0xFA  ❌  Device receive error (buffer overrun, framing error)
0xF0  ❌  Data received OK but flash write failed
0xF2  ❌  Firmware size exceeds device flash capacity
0xF3  ❌  Packet format error (header mismatch)
0xF4  ❌  Packet out of sequence (wrong packet number)
0xF5  ❌  Flash erase failed
```

#### ACK Validation in file_thread
```csharp
// After RevFlag = true  (Form1.cs:613)
if (RevFlag
    && ReceiveBytes[1] == 0x08           // function code matches
    && ReceiveBytes[2]*256 + ReceiveBytes[3] == packageNo)  // seq# matches
{
    if (ReceiveBytes[5] == 0xF1)  → success, next packet
    if (ReceiveBytes[5] == 0xFA/F0/F2/F3/F4/F5) → abort upgrade
}
```

---

## PART C — Side-by-Side Protocol Comparison

```
Feature               Custom Proto (winMark=3)    Modbus-RTU (winMark=4)
────────────────────  ─────────────────────────   ──────────────────────
Baud Rate             38400                        115200
Start Identifier      0xF1 (byte[0])               0x00 Device Addr (byte[0])
Function Code pos     byte[1]                       byte[1]
Frame Length          Fixed (8 or 200 or 48)        Variable (10 + DataNum + 2)
Endianness            Big-endian throughout          Big-endian for fields
CRC Algorithm         Lookup-table CRC-16           XOR-shift CRC-16
CRC Byte Order        HIGH then LOW                 LOW then HIGH (Modbus)
CRC Scope             bytes[0 .. n-3]               bytes[0 .. n-3]
RX CRC Verify         computed == last 2 bytes       CRC over all 8 bytes == 0
Max TX payload        200 bytes (save params)        10 + 512 = 522 bytes/pkt
RX frame size         8 or 200 bytes                8 bytes (fixed ACK)
Sync/Recovery         Slide on bad byte[0]/[1]      Slide on bad byte[1]
Thread model          data_thread (periodic)         file_thread (sequential)
Timeout               none (25ms timer drives it)   30s handshake, 5s/pkt
```

---

## PART D — End-to-End Call Chain

### D.1 TX Path (Custom Protocol)
```
25ms Timer fires
  └─► TimedEvent_InterruptB()
        └─► data_send_start()  →  spawns data_thread
              └─► Send_UpgradeData()
                    ├─► readDrivePara(0xF1, 0x91, 8)
                    │     └─► fills send_buf[0..7]
                    │
                    ├─► conver_sendParameter(8)
                    │     └─► copies send_buf → send_gloBuf
                    │
                    └─► uart_sendFun1(8)
                          └─► serial.Write(send_gloBuf, 0, 8)
                                └─► UART → RS-485 wire → Controller
```

### D.2 RX Path (Custom Protocol)
```
UART data arrives
  └─► serial_DataReceived() [interrupt]
        ├─► serial.Read() → append to Rev_Byte_buffer
        ├─► sliding-window sync (search for 0xF1 + valid fn)
        ├─► wait until uart_ReceByteLength bytes collected
        ├─► CRC16_R() verify
        ├─► copy to display_Data[0..199]
        └─► BeginInvoke(InitViewAB)
              └─► dis_Refresh()  ← unpacks all fields → UI labels/textboxes
```

### D.3 TX Path (Firmware Upgrade)
```
AutoUpgrade button → sets global.refreshFirmware_startMark=1
  └─► TimedEvent_InterruptB() sees startMark==2
        ├─► serial_checkPort_w4()  (switch to 115200)
        └─► file_send_start()  →  spawns file_thread
              └─► Send_UpgradeFile()
                    ├─► [Pkg 0a] send_byte_buffer(0,0x08,0,2,[AA,AA],total,0)
                    │     └─► serial.Write() → wire
                    │
                    ├─► [Pkg 0b] send_byte_buffer(0,0x08,0,2,[AA,01],total,0)
                    │     └─► serial.Write() → wire
                    │
                    └─► [Pkg 1..N] loop:
                          byte[] chunk = BinaryReader.ReadBytes(512)
                          send_byte_buffer(0,0x08,pkgNo,512,chunk,remaining,0)
                            └─► serial.Write() → wire
                          wait for RevFlag == true (set by DataReceived)
```

### D.4 RX Path (Firmware Upgrade)
```
UART data arrives (8-byte ACK from controller)
  └─► serial_DataReceived() [interrupt, same handler]
        ├─► serial.Read() → Rev_Byte_buffer
        ├─► check byte[1] in {0x08, 0x09, 0x06}
        ├─► wait for 8 bytes
        ├─► calc_modbus_crc(ReceiveBytes,8) == [0,0] ?
        └─► RevFlag = true  ←  unblocks file_thread's while(!RevFlag) loop
```
