// FUNCTION_BLOCK - one instance = one Finder 7M.24 meter
FUNCTION_BLOCK FB_EnergyMeter
VAR_INPUT
    xCommError        : BOOL;                   // <device>.xError of the Modbus server (COM) instance
    uiModbusErrorCode : UINT;                   // <device>.byModbusError (MB_ErrorCodes)
    awPower           : ARRAY[0..11] OF WORD;
    awCurrent         : ARRAY[0..1] OF WORD;
    awEnergyExp       : ARRAY[0..3] OF WORD;
    awEnergyMant      : ARRAY[0..7] OF WORD;
    awIdentity        : ARRAY[0..11] OF WORD;
    awQuality         : ARRAY[0..25] OF WORD;   // 32570..32595 (map v2, 25.11.2026)
    awTemp            : ARRAY[0..1] OF WORD;    // 32658..32659
    awRunTime         : ARRAY[0..1] OF WORD;    // 32480..32481
    xSwapWords        : BOOL := FALSE;          // Finder 7M.24: high word first -> FALSE
    tErrorHold        : TIME := T#3S;           // COMM_ERROR is cleared only after this time without any error
END_VAR
VAR_OUTPUT
    rActivePower_W     : REAL;
    rReactivePower_var : REAL;
    rApparentPower_VA  : REAL;
    rPowerFactor       : REAL;
    rFrequency_Hz      : REAL;
    rVoltage_V         : REAL;
    rCurrent_A         : REAL;
    diEnergyImportMant : DINT;   // n1, Wh = mant * 10^exp
    iEnergyImportExp   : INT;
    diEnergyExportMant : DINT;   // n3
    iEnergyExportExp   : INT;
    rEnergyImport_kWh  : REAL;
    rEnergyExport_kWh  : REAL;
    diReactivePosMant  : DINT;   // n2 (energy at Q > 0), varh = mant * 10^exp
    iReactivePosExp    : INT;
    diReactiveNegMant  : DINT;   // n4 (energy at Q < 0)
    iReactiveNegExp    : INT;
    rThdVoltage_pct    : REAL;   // THD U1, 32594
    rThdCurrent_pct    : REAL;   // THD I1, 32588
    rPhaseAngle_deg    : REAL;   // angle U1-I1, 32570 (negative at Q < 0, measured 25.11.2026)
    rTemperature_C     : REAL;   // internal meter temperature, 32658
    rRunTime_s         : REAL;   // meter run time, 32480
    awSerial           : ARRAY[0..3] OF WORD;
    sSerial            : STRING(8);
    uiStatus           : UINT;   // 0 = OK, 1 = COMM_ERROR, 2 = NO_DATA (no answer since start)
    uiErrorCode        : UINT;   // last non-zero MB_ErrorCodes value while not OK, 0 when OK
    uiErrorCount       : UINT;   // number of communication outages since start (wraps at 65535)
    udiDataAge_ms      : UDINT;  // 0 when OK; time since last confirmed OK state otherwise
END_VAR
VAR CONSTANT
    STATUS_OK         : UINT := 0;
    STATUS_COMM_ERROR : UINT := 1;
    STATUS_NO_DATA    : UINT := 2;
END_VAR
VAR
    xErrorSeen       : BOOL;   // at least one raw error since start
    xErrorActive     : BOOL;   // debounced error: raw error within the last tErrorHold
    xErrorActivePrev : BOOL;
    xDataSeen        : BOOL;
    tNow             : TIME;
    tLastOk          : TIME;
    tLastErr         : TIME;
    uiLastErrCode    : UINT;
    uConv            : U_Word32;
    pbySerial        : POINTER TO BYTE;
    i                : INT;
END_VAR
// --- code ---
// 1. Communication status (debounced: xError of the COM device drops between transactions;
//    fixed 23.11.2026 after checklist test 5)
tNow := TIME();
IF xCommError THEN
    xErrorSeen := TRUE;
    tLastErr   := tNow;
    IF uiModbusErrorCode <> 0 THEN
        uiLastErrCode := uiModbusErrorCode;
    END_IF
END_IF

xErrorActive := xErrorSeen AND ((tNow - tLastErr) < tErrorHold);

IF NOT xErrorActive THEN
    tLastOk := tNow;
END_IF
IF xErrorActive AND NOT xErrorActivePrev THEN
    uiErrorCount := uiErrorCount + 1;            // one outage = one count
END_IF
xErrorActivePrev := xErrorActive;

// Meter has answered at least once when the serial number registers are not zero
IF (awIdentity[8] <> 0) OR (awIdentity[9] <> 0) THEN
    xDataSeen := TRUE;
END_IF

IF NOT xDataSeen THEN
    uiStatus      := STATUS_NO_DATA;
    uiErrorCode   := uiLastErrCode;
    udiDataAge_ms := 16#FFFFFFFF;
ELSIF xErrorActive THEN
    uiStatus      := STATUS_COMM_ERROR;
    uiErrorCode   := uiLastErrCode;
    udiDataAge_ms := TIME_TO_UDINT(tNow - tLastOk);
ELSE
    uiStatus      := STATUS_OK;
    uiErrorCode   := 0;
    uiLastErrCode := 0;
    udiDataAge_ms := 0;
END_IF

// 2. Instantaneous values (IEEE 754 block 32490..32501, 32516)
rActivePower_W     := FC_WordsToReal(wFirst := awPower[0],  wSecond := awPower[1],  xSwapWords := xSwapWords);
rReactivePower_var := FC_WordsToReal(wFirst := awPower[2],  wSecond := awPower[3],  xSwapWords := xSwapWords);
rApparentPower_VA  := FC_WordsToReal(wFirst := awPower[4],  wSecond := awPower[5],  xSwapWords := xSwapWords);
rPowerFactor       := FC_WordsToReal(wFirst := awPower[6],  wSecond := awPower[7],  xSwapWords := xSwapWords);
rFrequency_Hz      := FC_WordsToReal(wFirst := awPower[8],  wSecond := awPower[9],  xSwapWords := xSwapWords);
rVoltage_V         := FC_WordsToReal(wFirst := awPower[10], wSecond := awPower[11], xSwapWords := xSwapWords);
rCurrent_A         := FC_WordsToReal(wFirst := awCurrent[0], wSecond := awCurrent[1], xSwapWords := xSwapWords);

// 3. Energy counters: Wh = mantissa * 10^exponent (n1 = import, n3 = export - to confirm on display)
uConv.dwRaw := FC_WordsToDword(wFirst := awEnergyMant[0], wSecond := awEnergyMant[1], xSwapWords := xSwapWords);
diEnergyImportMant := uConv.diInt;
iEnergyImportExp   := WORD_TO_INT(awEnergyExp[0]);

uConv.dwRaw := FC_WordsToDword(wFirst := awEnergyMant[4], wSecond := awEnergyMant[5], xSwapWords := xSwapWords);
diEnergyExportMant := uConv.diInt;
iEnergyExportExp   := WORD_TO_INT(awEnergyExp[2]);

rEnergyImport_kWh := LREAL_TO_REAL(DINT_TO_LREAL(diEnergyImportMant) * EXPT(LREAL#10.0, INT_TO_LREAL(iEnergyImportExp)) / 1000.0);
rEnergyExport_kWh := LREAL_TO_REAL(DINT_TO_LREAL(diEnergyExportMant) * EXPT(LREAL#10.0, INT_TO_LREAL(iEnergyExportExp)) / 1000.0);

// 3b. Reactive energy counters (map v2): n2 = mant[2..3] / exp[1], n4 = mant[6..7] / exp[3]
uConv.dwRaw := FC_WordsToDword(wFirst := awEnergyMant[2], wSecond := awEnergyMant[3], xSwapWords := xSwapWords);
diReactivePosMant := uConv.diInt;
iReactivePosExp   := WORD_TO_INT(awEnergyExp[1]);

uConv.dwRaw := FC_WordsToDword(wFirst := awEnergyMant[6], wSecond := awEnergyMant[7], xSwapWords := xSwapWords);
diReactiveNegMant := uConv.diInt;
iReactiveNegExp   := WORD_TO_INT(awEnergyExp[3]);

// 3c. Power quality, temperature, run time (map v2; values checked online in step PLC-1, 25.11.2026)
rPhaseAngle_deg := FC_WordsToReal(wFirst := awQuality[0],  wSecond := awQuality[1],  xSwapWords := xSwapWords);
rThdCurrent_pct := FC_WordsToReal(wFirst := awQuality[18], wSecond := awQuality[19], xSwapWords := xSwapWords);
rThdVoltage_pct := FC_WordsToReal(wFirst := awQuality[24], wSecond := awQuality[25], xSwapWords := xSwapWords);
rTemperature_C  := FC_WordsToReal(wFirst := awTemp[0],     wSecond := awTemp[1],     xSwapWords := xSwapWords);
rRunTime_s      := FC_WordsToReal(wFirst := awRunTime[0],  wSecond := awRunTime[1],  xSwapWords := xSwapWords);

// 4. Serial number (registers 30009..30012, ASCII, high byte first)
pbySerial := ADR(sSerial);
FOR i := 0 TO 3 DO
    awSerial[i]           := awIdentity[8 + i];
    pbySerial[2 * i]      := WORD_TO_BYTE(SHR(awIdentity[8 + i], 8));
    pbySerial[2 * i + 1]  := WORD_TO_BYTE(awIdentity[8 + i]);
END_FOR
pbySerial[8] := 0;
