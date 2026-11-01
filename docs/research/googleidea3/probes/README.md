# probes/ — checks that back the googleidea3 part docs

## snippet-as-is.c — does the monolith compile?

`googleidea3.md` presents its code as "a fully complete, single-source,
copy-pasteable monolithic codebase". This file is the document's interrupt
handler and IRQ-init (`googleidea3.md` lines 518–551) **verbatim**, wrapped
only with the type and macro definitions the document's own `main.c`
supplies (its lines 279–348). No other edits.

    gcc -c -Wall -Wextra -o /dev/null snippet-as-is.c

Result (ProArt host gcc, 2026-11-01; any C compiler says the same — these
are C rules, not target rules):

```
snippet-as-is.c:31:18:  error: unknown type name 'u16'
snippet-as-is.c:54:48:  error: lvalue required as left operand of assignment
snippet-as-is.c:60:29:  error: lvalue required as left operand of assignment
snippet-as-is.c:65:29:  error: lvalue required as left operand of assignment
snippet-as-is.c:66:35:  error: lvalue required as left operand of assignment
snippet-as-is.c:67:29:  error: lvalue required as left operand of assignment
```

Two distinct document bugs:

1. `main.c` uses `u16 active_edges` (its line 336) but typedefs only `u32`,
   `u8`, `u64` (its lines 316–318). The monolith's own type set is missing
   a type it uses.
2. Every register *write* in the interrupt handler and the IRQ init is an
   assignment to a cast of a literal — `(volatile u32)GICD_CTLR = 0x3;` —
   which is not an lvalue in C. Five such writes; five errors. The code has
   never been compiled.

And one silent bug the compiler does not catch: the register *reads* in the
same handler (`u32 head = (volatile u32)REG_NIC_INGRESS_HEAD;`) compile
cleanly but load the **address constant** (0x20000000), not the contents of
the register — the value-cast idiom instead of a pointer dereference. The
document mixes three register-access idioms (`*(volatile u32*)REG` —
correct; `(volatile u32)REG = x` — illegal; `u32 v = (volatile u32)REG` —
legal but wrong), and only the first is right.

Run time: under a second. Needs: any C compiler.
