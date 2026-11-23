// DUT (UNION) - reinterprets 32 bits as DWORD, REAL or DINT
TYPE U_Word32 :
UNION
    dwRaw : DWORD;
    rReal : REAL;
    diInt : DINT;
END_UNION
END_TYPE
