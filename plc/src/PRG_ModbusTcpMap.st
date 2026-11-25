// PROGRAM - reads meter(s) via FB_EnergyMeter and fills Modbus TCP input registers (map v2)
PROGRAM PRG_ModbusTcpMap
VAR CONSTANT
    MAP_VERSION     : WORD := 2;   // v2 since 25.11.2026 (E2-PLC2)
    REG_HEARTBEAT   : INT := 0;   // 0..1  UDINT
    REG_MAP_VERSION : INT := 2;   // 2     UINT
    METER1_BASE     : INT := 10;  // meter block: base .. base+49

    // offsets inside a meter block
    OFS_STATUS      : INT := 0;   // UINT
    OFS_ERROR_CODE  : INT := 1;   // UINT
    OFS_ERROR_COUNT : INT := 2;   // UINT
    OFS_DATA_AGE    : INT := 4;   // UDINT, ms
    OFS_P           : INT := 6;   // REAL, W
    OFS_Q           : INT := 8;   // REAL, var
    OFS_S           : INT := 10;  // REAL, VA
    OFS_PF          : INT := 12;  // REAL
    OFS_F           : INT := 14;  // REAL, Hz
    OFS_U           : INT := 16;  // REAL, V
    OFS_I           : INT := 18;  // REAL, A
    OFS_E_IMP       : INT := 20;  // REAL, kWh
    OFS_E_EXP       : INT := 22;  // REAL, kWh
    OFS_E_IMP_MANT  : INT := 24;  // DINT
    OFS_E_IMP_EXP   : INT := 26;  // INT
    OFS_E_EXP_MANT  : INT := 27;  // DINT
    OFS_E_EXP_EXP   : INT := 29;  // INT
    OFS_SERIAL      : INT := 30;  // 4 x WORD, ASCII
    // map v2
    OFS_Q_POS_MANT  : INT := 34;  // DINT, n2
    OFS_Q_POS_EXP   : INT := 36;  // INT
    OFS_Q_NEG_MANT  : INT := 37;  // DINT, n4
    OFS_Q_NEG_EXP   : INT := 39;  // INT
    OFS_THD_U       : INT := 40;  // REAL, %
    OFS_THD_I       : INT := 42;  // REAL, %
    OFS_ANGLE       : INT := 44;  // REAL, deg
    OFS_TEMP        : INT := 46;  // REAL, degC
    OFS_RUN_TIME    : INT := 48;  // REAL, s
END_VAR
VAR
    udiHeartbeat : UDINT;
    fbMeter1     : FB_EnergyMeter;
    iBase        : INT;
    i            : INT;
END_VAR
// --- code ---
// 1. Meter 1: Finder 7M.24 on COM (Modbus_Server_COM_Port, address 2)
fbMeter1(
    xCommError        := Modbus_Server_COM_Port.xError,
    uiModbusErrorCode := TO_UINT(Modbus_Server_COM_Port.byModbusError),
    awPower           := GVL_Meter.awFinder1Power,
    awCurrent         := GVL_Meter.awFinder1Current,
    awEnergyExp       := GVL_Meter.awFinder1EnergyExp,
    awEnergyMant      := GVL_Meter.awFinder1EnergyMant,
    awIdentity        := GVL_Meter.awFinder1Identity,
    awQuality         := GVL_Meter.awFinder1Quality,
    awTemp            := GVL_Meter.awFinder1Temp,
    awRunTime         := GVL_Meter.awFinder1RunTime,
    xSwapWords        := FALSE);

// 2. Header
udiHeartbeat := udiHeartbeat + 1;
FC_PutDword(awRegs := GVL_Meter.awTcpInputRegs, iIndex := REG_HEARTBEAT, dwValue := UDINT_TO_DWORD(udiHeartbeat));
GVL_Meter.awTcpInputRegs[REG_MAP_VERSION] := MAP_VERSION;

// 3. Meter 1 block
iBase := METER1_BASE;
GVL_Meter.awTcpInputRegs[iBase + OFS_STATUS]      := UINT_TO_WORD(fbMeter1.uiStatus);
GVL_Meter.awTcpInputRegs[iBase + OFS_ERROR_CODE]  := UINT_TO_WORD(fbMeter1.uiErrorCode);
GVL_Meter.awTcpInputRegs[iBase + OFS_ERROR_COUNT] := UINT_TO_WORD(fbMeter1.uiErrorCount);
FC_PutDword(awRegs := GVL_Meter.awTcpInputRegs, iIndex := iBase + OFS_DATA_AGE, dwValue := UDINT_TO_DWORD(fbMeter1.udiDataAge_ms));

FC_PutReal(awRegs := GVL_Meter.awTcpInputRegs, iIndex := iBase + OFS_P,  rValue := fbMeter1.rActivePower_W);
FC_PutReal(awRegs := GVL_Meter.awTcpInputRegs, iIndex := iBase + OFS_Q,  rValue := fbMeter1.rReactivePower_var);
FC_PutReal(awRegs := GVL_Meter.awTcpInputRegs, iIndex := iBase + OFS_S,  rValue := fbMeter1.rApparentPower_VA);
FC_PutReal(awRegs := GVL_Meter.awTcpInputRegs, iIndex := iBase + OFS_PF, rValue := fbMeter1.rPowerFactor);
FC_PutReal(awRegs := GVL_Meter.awTcpInputRegs, iIndex := iBase + OFS_F,  rValue := fbMeter1.rFrequency_Hz);
FC_PutReal(awRegs := GVL_Meter.awTcpInputRegs, iIndex := iBase + OFS_U,  rValue := fbMeter1.rVoltage_V);
FC_PutReal(awRegs := GVL_Meter.awTcpInputRegs, iIndex := iBase + OFS_I,  rValue := fbMeter1.rCurrent_A);
FC_PutReal(awRegs := GVL_Meter.awTcpInputRegs, iIndex := iBase + OFS_E_IMP, rValue := fbMeter1.rEnergyImport_kWh);
FC_PutReal(awRegs := GVL_Meter.awTcpInputRegs, iIndex := iBase + OFS_E_EXP, rValue := fbMeter1.rEnergyExport_kWh);

FC_PutDword(awRegs := GVL_Meter.awTcpInputRegs, iIndex := iBase + OFS_E_IMP_MANT, dwValue := DINT_TO_DWORD(fbMeter1.diEnergyImportMant));
GVL_Meter.awTcpInputRegs[iBase + OFS_E_IMP_EXP] := INT_TO_WORD(fbMeter1.iEnergyImportExp);
FC_PutDword(awRegs := GVL_Meter.awTcpInputRegs, iIndex := iBase + OFS_E_EXP_MANT, dwValue := DINT_TO_DWORD(fbMeter1.diEnergyExportMant));
GVL_Meter.awTcpInputRegs[iBase + OFS_E_EXP_EXP] := INT_TO_WORD(fbMeter1.iEnergyExportExp);

FOR i := 0 TO 3 DO
    GVL_Meter.awTcpInputRegs[iBase + OFS_SERIAL + i] := fbMeter1.awSerial[i];
END_FOR


// 4. Map v2: registers 44..59 (offsets 34..49)
FC_PutDword(awRegs := GVL_Meter.awTcpInputRegs, iIndex := iBase + OFS_Q_POS_MANT, dwValue := DINT_TO_DWORD(fbMeter1.diReactivePosMant));
GVL_Meter.awTcpInputRegs[iBase + OFS_Q_POS_EXP] := INT_TO_WORD(fbMeter1.iReactivePosExp);
FC_PutDword(awRegs := GVL_Meter.awTcpInputRegs, iIndex := iBase + OFS_Q_NEG_MANT, dwValue := DINT_TO_DWORD(fbMeter1.diReactiveNegMant));
GVL_Meter.awTcpInputRegs[iBase + OFS_Q_NEG_EXP] := INT_TO_WORD(fbMeter1.iReactiveNegExp);
FC_PutReal(awRegs := GVL_Meter.awTcpInputRegs, iIndex := iBase + OFS_THD_U,    rValue := fbMeter1.rThdVoltage_pct);
FC_PutReal(awRegs := GVL_Meter.awTcpInputRegs, iIndex := iBase + OFS_THD_I,    rValue := fbMeter1.rThdCurrent_pct);
FC_PutReal(awRegs := GVL_Meter.awTcpInputRegs, iIndex := iBase + OFS_ANGLE,    rValue := fbMeter1.rPhaseAngle_deg);
FC_PutReal(awRegs := GVL_Meter.awTcpInputRegs, iIndex := iBase + OFS_TEMP,     rValue := fbMeter1.rTemperature_C);
FC_PutReal(awRegs := GVL_Meter.awTcpInputRegs, iIndex := iBase + OFS_RUN_TIME, rValue := fbMeter1.rRunTime_s);
