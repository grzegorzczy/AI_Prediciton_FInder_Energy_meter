// FUNCTION, return type DWORD
FUNCTION FC_WordsToDword : DWORD
VAR_INPUT
    wFirst     : WORD;  // register with lower address
    wSecond    : WORD;  // register with higher address
    xSwapWords : BOOL;  // FALSE = first register is the high word (Finder 7M.24, verified 23.11.2026)
END_VAR
// --- code ---
IF xSwapWords THEN
    FC_WordsToDword := SHL(WORD_TO_DWORD(wSecond), 16) OR WORD_TO_DWORD(wFirst);
ELSE
    FC_WordsToDword := SHL(WORD_TO_DWORD(wFirst), 16) OR WORD_TO_DWORD(wSecond);
END_IF
