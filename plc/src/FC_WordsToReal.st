// FUNCTION, return type REAL
FUNCTION FC_WordsToReal : REAL
VAR_INPUT
    wFirst     : WORD;
    wSecond    : WORD;
    xSwapWords : BOOL;
END_VAR
VAR
    uConv : U_Word32;
END_VAR
// --- code ---
uConv.dwRaw := FC_WordsToDword(wFirst := wFirst, wSecond := wSecond, xSwapWords := xSwapWords);
FC_WordsToReal := uConv.rReal;
