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
    xSwapWords        : BOOL := FALSE;          // Finder 7M.24: high word first -> FALSE
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
    awSerial           : ARRAY[0..3] OF WORD;
    sSerial            : STRING(8);
    uiStatus           : UINT;   // 0 = OK, 1 = COMM_ERROR, 2 = NO_DATA (no answer since start)
    uiErrorCode        : UINT;
    uiErrorCount       : UINT;   // rising edges of xCommError since start (wraps at 65535)
    udiDataAge_ms      : UDINT;  // 0 when OK; time since last error-free cycle otherwise
END_VAR
VAR CONSTANT
    STATUS_OK         : UINT := 0;
    STATUS_COMM_ERROR : UINT := 1;
    STATUS_NO_DATA    : UINT := 2;
END_VAR
VAR
    xErrorPrev : BOOL;
    xDataSeen  : BOOL;
    tNow       : TIME;
    tLastOk    : TIME;
    uConv      : U_Word32;
    pbySerial  : POINTER TO BYTE;
    i          : INT;
END_VAR
// --- code ---
// 1. Communication status
tNow := TIME();
IF NOT xCommError THEN
    tLastOk := tNow;
END_IF
IF xCommError AND NOT xErrorPrev THEN
    uiErrorCount := uiErrorCount + 1;
END_IF
xErrorPrev  := xCommError;
uiErrorCode := uiModbusErrorCode;

// Meter has answered at least once when the serial number registers are not zero
IF (awIdentity[8] <> 0) OR (awIdentity[9] <> 0) THEN
    xDataSeen := TRUE;
END_IF

IF NOT xDataSeen THEN
    uiStatus      := STATUS_NO_DATA;
    udiDataAge_ms := 16#FFFFFFFF;
ELSIF xCommError THEN
    uiStatus      := STATUS_COMM_ERROR;
    udiDataAge_ms := TIME_TO_UDINT(tNow - tLastOk);
ELSE
    uiStatus      := STATUS_OK;
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

// 4. Serial number (registers 30009..30012, ASCII, high byte first)
pbySerial := ADR(sSerial);
FOR i := 0 TO 3 DO
    awSerial[i]           := awIdentity[8 + i];
    pbySerial[2 * i]      := WORD_TO_BYTE(SHR(awIdentity[8 + i], 8));
    pbySerial[2 * i + 1]  := WORD_TO_BYTE(awIdentity[8 + i]);
END_FOR
pbySerial[8] := 0;
