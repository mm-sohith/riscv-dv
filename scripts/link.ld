OUTPUT_ARCH( "riscv" )
ENTRY(_start)

SECTIONS
{
  . = 0x80000000;
  begin_signature = .;
  .text : { *(.text) }
  


  /* Pin .data so injected _self_check block never shifts anything below */
  /* . = 0x80100000; */
  
  .data   : { *(.data)  }
  .tohost : { *(.tohost) }
  . = ALIGN(0x1000);
  .page_table   : { *(.page_table)   }
  .user_stack   : { *(.user_stack)   }
  .kernel_data  : { *(.kernel_data)  }
  .kernel_stack : { *(.kernel_stack) }
  .bss          : { *(.bss)          }

  /* Signature region — floats above kernel stack, that's fine */
  . = ALIGN(8);
  .region_0 : { *(.region_0) }
  . = ALIGN(8);
  .region_1 : { *(.region_1) }
  . = ALIGN(8);

  end_signature = .;
  /* Reference region — pinned */
  . = 0x90000000;
  .ref : {
    _spike_ref_start = .;
    *(.data.ref)
    _spike_ref_end = .;
  }

  _end = .;
}