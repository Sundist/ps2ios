# Entry point and BIOS call stubs for the ps1-to-ios test ROM.
    .set noreorder
    .section .text.start, "ax"
    .globl _start
_start:
    la    $sp, 0x801FFF00
    la    $t0, __bss_start
    la    $t1, __bss_end
1:  beq   $t0, $t1, 2f
    nop
    sw    $zero, 0($t0)
    b     1b
    addiu $t0, $t0, 4
2:  jal   main
    nop
3:  b     3b
    nop

    .text
# BIOS function tables: jump to 0xA0/0xB0/0xC0 with the function number in $t1.
    .macro BIOSFN name, table, num
    .globl \name
\name:
    li    $t2, \table
    jr    $t2
    li    $t1, \num
    .endm

    BIOSFN InitPAD,        0xB0, 0x12
    BIOSFN StartPAD,       0xB0, 0x13
    BIOSFN ChangeClearPAD, 0xB0, 0x5B
