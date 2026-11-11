/* PS-X EXE layout: loaded at 0x80010000, entry _start. */
OUTPUT_FORMAT("elf32-tradlittlemips")
ENTRY(_start)
SECTIONS {
    . = 0x80010000;
    .text : { KEEP(*(.text.start)) *(.text .text.*) }
    .rodata : { *(.rodata .rodata.*) }
    .data : { *(.data .data.* .sdata .sdata.*) }
    . = ALIGN(4);
    __bss_start = .;
    .bss (NOLOAD) : { *(.bss .bss.* .sbss .sbss.* COMMON) }
    . = ALIGN(4);
    __bss_end = .;
    /DISCARD/ : { *(.MIPS.abiflags) *(.reginfo) *(.comment) *(.note*) *(.pdr) *(.gnu.attributes) }
}
