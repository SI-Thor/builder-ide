/* snippet-as-is.c — googleidea3.md's interrupt handler and IRQ init, verbatim
 * (source lines 518–551 of googleidea3.md), wrapped only with the type and
 * macro definitions the document itself supplies in its main.c (lines
 * 279–348). Compile check: does the "copy-pasteable monolithic codebase"
 * compile as written?
 *
 * Build: gcc -c -Wall -Wextra -o /dev/null snippet-as-is.c
 */
#include <stdint.h>

typedef unsigned int   u32;
typedef unsigned char  u8;
typedef unsigned long long u64;

#define REG_NIC_INGRESS_HEAD  0x20000000
#define REG_NIC_INGRESS_TAIL  0x20000004
#define ADDR_NIC_RX_RING      0x20001000
#define REG_GPU_ERROR_STATUS  0x60000000
#define MAX_CELLS             65536
#define RING_BUFFER_MASK      0x3FF

#define GICD_BASE               0x3D000000
#define GICD_CTLR               (GICD_BASE + 0x000)
#define GICD_ISENABLER0         (GICD_BASE + 0x100)
#define GICC_BASE               0x3D002000
#define GICC_IAR                (GICC_BASE + 0x00C)
#define GICC_EOIR               (GICC_BASE + 0x010)

typedef struct { u32 op; u32 src; u32 dest; u32 payload; } FlitFrame;
typedef struct { u32 cell_id; u32 activation_state; u32 threshold_trigger;
                 u16 active_edges; u8 reserved_padding[2]; u32 dials[4]; }
    QUF_Hardware_Cell;
static volatile QUF_Hardware_Cell* const FABRIC = (QUF_Hardware_Cell*)0x10000000;
u32 emit_graph_node(u32 method, u64 tensor_ptr, u64 sass_ptr);
void dispatch_graph_hardware(void);

/* ---------------- verbatim from googleidea3.md from here down ------------- */

void bare_metal_interrupt_handler(void) {
    u32 iar_value = *(volatile u32*)GICC_IAR;
    u32 interrupt_id = iar_value & 0x3FF;

    if (interrupt_id == 32) { // Inbound network frame arrived interrupt line
        u32 head = (volatile u32)REG_NIC_INGRESS_HEAD;
        u32 tail = (volatile u32)REG_NIC_INGRESS_TAIL;
        if (head != tail) {
            volatile FlitFrame* ring = (volatile FlitFrame*)ADDR_NIC_RX_RING;
            volatile FlitFrame* packet = &ring[head & RING_BUFFER_MASK];
            if (packet->dest < MAX_CELLS) {
                u64 target_cell_address = (u64)&FABRIC[packet->dest];
                emit_graph_node(packet->op, target_cell_address, 0);
                dispatch_graph_hardware();
            }
            (volatile u32)REG_NIC_INGRESS_HEAD = head + 1;
        }
    } else if (interrupt_id == 33) { // Telemetry Miter Error Flag line
        u32 failing_cell_id = (volatile u32)REG_GPU_ERROR_STATUS;
        (void)failing_cell_id;
    }
    (volatile u32)GICC_EOIR = iar_value;
    asm volatile("isb" ::: "memory");
}

void initialize_hardware_irq_routing(void) {
    (volatile u32)GICD_CTLR = 0x3;
    (volatile u32)GICD_ISENABLER0 = (1 << 0) | (1 << 1); // Unmask lines 32 & 33
    (volatile u32)GICC_BASE = 0x3;
    asm volatile("dmb ish" ::: "memory");
}
