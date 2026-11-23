// FUNCTION, return type BOOL - writes 32 bits into two registers, high word first
FUNCTION FC_PutDword : BOOL
VAR_IN_OUT
    awRegs : ARRAY[0..99] OF WORD;
END_VAR
VAR_INPUT
    iIndex  : INT;    // index of the first (high) register
    dwValue : DWORD;
END_VAR
// --- code ---
IF (iIndex < 0) OR (iIndex > 98) THEN
    FC_PutDword := FALSE;
    RETURN;
END_IF
awRegs[iIndex]     := DWORD_TO_WORD(SHR(dwValue, 16));
awRegs[iIndex + 1] := DWORD_TO_WORD(dwValue);
FC_PutDword := TRUE;
