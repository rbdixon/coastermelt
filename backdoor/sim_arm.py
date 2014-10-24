# Tiny and slow instruction simulator, for tracing firmware execution.
# CPU state is implemented as a flat regs[] array, with a few special indices.
# This can be small because it doesn't understand machine code, just assembly language.

from code import *


class SimARM:

    reg_names = ('r0', 'r1', 'r2', 'r3', 'r4', 'r5', 'r6', 'r7', 'r8', 'r9', 'r10', 'r11', 'r12', 'sp', 'lr', 'pc')

    def __init__(self, device):
        # Link with the device whose memory we'll be using
        self.device = device

        # State
        self.regs = [0] * 16
        self.cpsr = 0xc0000033
        self.thumb = False

        # Cache for disassembled instructions
        self.instructions = {}

        # Register lookup
        self.reg_numbers = {}
        for i, name in enumerate(self.reg_names):
            self.reg_numbers[name] = i

    def step(self):
        regs = self.regs
        instr = self.get_instruction(regs[15])
        regs[15] = instr.next_address
        getattr(self, 'op_' + instr.op)(instr.args)

    def load(self, address):
        data = self.device.peek(address)
        print "LOAD  [%08x] -> %08x" % (address, data)
        return data

    def store(self, address, data):
        print "STORE  [%08x] <- %08x" % (address, data)
        self.device.poke(address, data)

    def get_next_instruction(self):
        return self.get_instruction(self.regs[15])

    def get_instruction(self, addr):
        try:
            return self.instructions[addr]
        except KeyError:
            self._load_instruction(addr)
            return self.instructions[addr]

    def _load_instruction(self, addr, fetch_size = 32):
        lines = disassembly_lines(disassemble(self.device, addr, fetch_size, thumb=self.thumb))
        for i in range(len(lines) - 1):
            lines[i].next_address = lines[i+1].address
            self.instructions[lines[i].address] = lines[i]

    def op_ldr(self, args):
        left, right = args.split(', ', 1)
        assert right[0] == '['
        addrs = right.strip('[]').split(', ')
        v = self.regs[self.reg_numbers[addrs[0]]]
        if len(addrs) > 1:
            assert addrs[1][0] == '#'
            v = ((v + 4) & ~3) + int(addrs[1][1:], 0)
        self.regs[self.reg_numbers[left]] = self.load(v)

    def op_str(self, args):
        left, right = args.split(', ', 1)
        assert right[0] == '['
        addrs = right.strip('[]').split(', ')
        v = self.regs[self.reg_numbers[addrs[0]]]
        if len(addrs) > 1:
            assert addrs[1][0] == '#'
            v = ((v + 4) & ~3) + int(addrs[1][1:], 0)
        self.store(v, self.regs[self.reg_numbers[left]])

    def op_nop(self, args):
        pass

    def op_mov(self, args):
        dst, src = args.split(', ', 1)
        if src[0] == '#':
            self.regs[self.reg_numbers[dst]] = int(src[1:], 0)
        else:
            self.regs[self.reg_numbers[dst]] = self.regs[self.reg_numbers[src]]
