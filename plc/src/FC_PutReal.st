// FUNCTION, return type BOOL - writes REAL (IEEE 754) into two registers, high word first
FUNCTION FC_PutReal : BOOL
VAR_IN_OUT
    awRegs : ARRAY[0..99] OF WORD;
END_VAR
VAR_INPUT
    iIndex : INT;
    rValue : REAL;
END_VAR
VAR
    uConv : U_Word32;
END_VAR
// --- code ---
uConv.rReal := rValue;
FC_PutReal := FC_PutDword(awRegs := awRegs, iIndex := iIndex, dwValue := uConv.dwRaw);
