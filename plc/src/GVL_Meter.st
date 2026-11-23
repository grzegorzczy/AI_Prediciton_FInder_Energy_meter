// GVL - raw Modbus channels and Modbus TCP input registers
VAR_GLOBAL
    // Finder 7M.24 #1 (Modbus RTU address 2) - mapped in Modbus_Server_COM_Port I/O Mapping
    awFinder1Power      : ARRAY[0..11] OF WORD;  // 32490..32501: Pt, Qt, St, PFt, f, U1 (REAL, high word first)
    awFinder1Current    : ARRAY[0..1] OF WORD;   // 32516..32517: I1 (REAL)
    awFinder1EnergyExp  : ARRAY[0..3] OF WORD;   // 30401..30404: exponents n1..n4 (INT)
    awFinder1EnergyMant : ARRAY[0..7] OF WORD;   // 30406..30413: mantissas n1..n4 (DINT, high word first)
    awFinder1Identity   : ARRAY[0..11] OF WORD;  // 30001..30012: model (0..7) + serial (8..11), ASCII
    awFinder1MaxRegs    : ARRAY[0..0] OF WORD;   // 30099: max registers per request

    // Modbus TCP server input registers (FC04) - mapped in ModbusTCP_Server_Device I/O Mapping
    awTcpInputRegs      : ARRAY[0..99] OF WORD;
END_VAR
