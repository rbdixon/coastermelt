# The jankiest simulator for our janky debugger.
#
# Designed for tracing firmware execution, and untangling code flow while
# talking to actual in-system hardware. The ARM CPU runs (very slowly) in
# simulation in Python, proxying its I/O over a debug port. We need a debug
# port that owns its own main loop, so this doesn't work with the default
# SCSI/USB port, it requires the hardware hack %bitbang interface.
#
# CPU state is implemented as a flat regs[] array, with a few special indices.
# This can be small because it doesn't understand machine code, just assembly
# language. This is really more of an ARM assembly interpreter than a CPU
# simulator, but it'll be close enough.

__all__ = [ 'SimARM' ]

from code import *


class SimARM:
    def __init__(self, device):
        # Link with the device whose memory we'll be using
        self.device = device

        # State
        self.regs = [0] * 16
        self.thumb = False
        self.cpsrV = False
        self.cpsrC = False
        self.cpsrZ = False
        self.cpsrN = False

        # Special addresses
        self.skip_stores = {
            0x04020f24: "Power or GPIO init? Breaks bitbang backdoor.",
            0x04030f04: "Power or GPIO init? Breaks bitbang backdoor.",
            0x04030f44: "Power or GPIO init? Breaks bitbang backdoor.",
        }

        # Cache for disassembled instructions
        self.instructions = {}

        # Register lookup
        self.reg_names = ('r0', 'r1', 'r2', 'r3', 'r4', 'r5', 'r6', 'r7', 
                          'r8', 'r9', 'r10', 'r11', 'r12', 'sp', 'lr', 'pc')
        self.alt_names = ('a1', 'a2', 'a3', 'a4', 'v1', 'v2', 'v3', 'v4',
                          'v5', 'sb', 'sl', 'fp', 'ip', 'r13', 'r14', 'r15')
        self.reg_numbers = {}
        for i, name in enumerate(self.reg_names): self.reg_numbers[name] = i
        for i, name in enumerate(self.alt_names): self.reg_numbers[name] = i

        # Initialize ldm/stm variants
        for memop in ('ld', 'st'):
            for mode in ('', 'ia', 'ib', 'da', 'db'):
                self._generate_ldstm(memop, mode)

        # Initialize condition codes
        for name in self.__class__.__dict__.keys():
            if name.startswith('op_'):
                self._generate_condition_codes(getattr(self, name), name + '%s')

    def _generate_ldstm(self, memop, mode):
        impl = mode or 'ia'
        def fn(args):
            left, right = args.split(', ', 1)
            assert right[0] == '{'
            writeback = left.endswith('!')
            left = self.reg_numbers[left.strip('!')]
            regs = right.strip('{}').split(', ')
            addr = self.regs[left]
            
            for r in regs:
                if impl == 'ib': addr += 4
                if impl == 'db': addr -= 4
                if memop == 'st':
                    self.store(addr, self.regs[self.reg_numbers[r]])
                else:
                    self._dstpc(r, self.load(addr))
                if impl == 'ia': addr += 4
                if impl == 'da': addr -= 4

            if writeback:
                self.regs[left] = addr

        setattr(self, 'op_' + memop + 'm' + mode, fn)
        self._generate_condition_codes(fn, 'op_' + memop + 'm%s' + mode)
        self._generate_condition_codes(fn, 'op_' + memop + 'm' + mode + '%s')

    def _generate_condition_codes(self, fn, name):
        setattr(self, name % 'eq', lambda args, fn=fn: (self.cpsrZ     ) and fn(args))
        setattr(self, name % 'ne', lambda args, fn=fn: (not self.cpsrZ ) and fn(args))
        setattr(self, name % 'cs', lambda args, fn=fn: (self.cpsrC     ) and fn(args))
        setattr(self, name % 'hs', lambda args, fn=fn: (self.cpsrC     ) and fn(args))
        setattr(self, name % 'cc', lambda args, fn=fn: (not self.cpsrC ) and fn(args))
        setattr(self, name % 'lo', lambda args, fn=fn: (not self.cpsrC ) and fn(args))
        setattr(self, name % 'mi', lambda args, fn=fn: (self.cpsrN     ) and fn(args))
        setattr(self, name % 'pl', lambda args, fn=fn: (not self.cpsrN ) and fn(args))
        setattr(self, name % 'vs', lambda args, fn=fn: (self.cpsrV     ) and fn(args))
        setattr(self, name % 'vc', lambda args, fn=fn: (not self.cpsrV ) and fn(args))
        setattr(self, name % 'hi', lambda args, fn=fn: (self.cpsrC and not self.cpsrZ ) and fn(args))
        setattr(self, name % 'ls', lambda args, fn=fn: (self.cpsrZ and not self.cpsrC ) and fn(args))
        setattr(self, name % 'ge', lambda args, fn=fn: (((not not self.cpsrN) == (not not self.cpsrV)) ) and fn(args))
        setattr(self, name % 'lt', lambda args, fn=fn: (((not not self.cpsrN) != (not not self.cpsrV)) ) and fn(args))
        setattr(self, name % 'gt', lambda args, fn=fn: (((not not self.cpsrN) == (not not self.cpsrV)) and not self.cpsrZ ) and fn(args))
        setattr(self, name % 'le', lambda args, fn=fn: (((not not self.cpsrN) != (not not self.cpsrV)) or self.cpsrZ      ) and fn(args))
        setattr(self, name % 'al', fn)

    def step(self):
        regs = self.regs
        instr = self.get_instruction(regs[15])
        self._branch = None

        # Inside the instruction, PC reads as PC+8
        regs[15] += 8
        try:
            getattr(self, 'op_' + instr.op)(instr.args)
            regs[15] = self._branch or instr.next_address
        except:
            regs[15] = instr.address
            raise

    def load(self, address):
        data = self.device.peek(address)
        print "LOAD  [%08x] -> %08x" % (address, data)
        return data

    def store(self, address, data):
        if address in self.skip_stores:
            print "STORE [%08x] <- %08x (skipped: %s)" % (address, data, self.skip_stores[address])
        else:
            print "STORE [%08x] <- %08x" % (address, data)
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

    def _reg_or_literal(self, s):
        if s[0] == '#':
            return int(s[1:], 0)
        return self.regs[self.reg_numbers[s]]

    @staticmethod
    def _3arg(args):
        l = args.split(', ')
        if len(l) == 3:
            return l
        else:
            return [l[0]] + l

    def _dstpc(self, dst, r):
        if dst == 'pc':
            self._branch = r
        else:
            self.regs[self.reg_numbers[dst]] = r

    def op_ldr(self, args):
        left, right = args.split(', ', 1)
        assert right[0] == '['
        addrs = right.strip('[]').split(', ')
        v = self.regs[self.reg_numbers[addrs[0]]]
        if len(addrs) > 1:
            assert addrs[1][0] == '#'
            v = (v & ~3) + int(addrs[1][1:], 0)
        self._dstpc(left, self.load(v))

    def op_str(self, args):
        left, right = args.split(', ', 1)
        assert right[0] == '['
        addrs = right.strip('[]').split(', ')
        v = self.regs[self.reg_numbers[addrs[0]]]
        if len(addrs) > 1:
            assert addrs[1][0] == '#'
            v = (v & ~3) + int(addrs[1][1:], 0)
        self.store(v, self.regs[self.reg_numbers[left]])

    def op_bx(self, args):
        r = self.regs[self.reg_numbers[args]]
        self._branch = r & ~1
        self.thumb = r & 1

    def op_b(self, args):
        self._branch = int(args, 0)

    def op_nop(self, args):
        pass

    def op_mov(self, args):
        dst, src = args.split(', ', 1)
        self._dstpc(dst, self._reg_or_literal(src))

    def op_bic(self, args):
        dst, src0, src1 = self._3arg(args)
        r = self.regs[self.reg_numbers[src0]] & ~self._reg_or_literal(src1)
        self._dstpc(dst, r)

    def op_orr(self, args):
        dst, src0, src1 = self._3arg(args)
        r = self.regs[self.reg_numbers[src0]] | self._reg_or_literal(src1)
        self._dstpc(dst, r)

    def op_orrs(self, args):
        dst, src0, src1 = self._3arg(args)
        r = self.regs[self.reg_numbers[src0]] | self._reg_or_literal(src1)
        self.cpsrZ = r == 0
        self.cpsrN = r >> 31
        self._dstpc(dst, r)

    def op_and(self, args):
        dst, src0, src1 = self._3arg(args)
        r = self.regs[self.reg_numbers[src0]] & self._reg_or_literal(src1)
        self._dstpc(dst, r)

    def op_ands(self, args):
        dst, src0, src1 = self._3arg(args)
        r = self.regs[self.reg_numbers[src0]] & self._reg_or_literal(src1)
        self.cpsrZ = r == 0
        self.cpsrN = r >> 31
        self._dstpc(dst, r)

    def op_tst(self, args):
        dst, src0, src1 = self._3arg(args)
        r = self.regs[self.reg_numbers[src0]] & self._reg_or_literal(src1)
        self.cpsrZ = r == 0
        self.cpsrN = r >> 31

    def op_eor(self, args):
        dst, src0, src1 = self._3arg(args)
        r = self.regs[self.reg_numbers[src0]] ^ self._reg_or_literal(src1)
        self._dstpc(dst, r)

    def op_eors(self, args):
        dst, src0, src1 = self._3arg(args)
        r = self.regs[self.reg_numbers[src0]] ^ self._reg_or_literal(src1)
        self.cpsrZ = r == 0
        self.cpsrN = r >> 31
        self._dstpc(dst, r)
        
    def op_add(self, args):
        dst, src0, src1 = self._3arg(args)
        r = self.regs[self.reg_numbers[src0]] + self._reg_or_literal(src1)
        self._dstpc(dst, r & 0xffffffff)

    def op_sub(self, args):
        dst, src0, src1 = self._3arg(args)
        r = self.regs[self.reg_numbers[src0]] - self._reg_or_literal(src1)
        self._dstpc(dst, r & 0xffffffff)

    def op_subs(self, args):
        dst, src0, src1 = self._3arg(args)
        a = self.regs[self.reg_numbers[src0]]
        b = self._reg_or_literal(src1)
        r = a - b
        self.cpsrN = r >> 31
        self.cpsrZ = not (r & 0xffffffff)
        self.cpsrC = (a & 0xffffffff) >= (b & 0xffffffff)
        self.cpsrV = (a >> 31) != (b >> 31) and (a >> 31) != (r >> 31)
        self._dstpc(dst, r & 0xffffffff)

    def op_cmp(self, args):
        dst, src0, src1 = self._3arg(args)
        a = self.regs[self.reg_numbers[src0]]
        b = self._reg_or_literal(src1)
        r = a - b
        self.cpsrN = r >> 31
        self.cpsrZ = not (r & 0xffffffff)
        self.cpsrC = (a & 0xffffffff) >= (b & 0xffffffff)
        self.cpsrV = (a >> 31) != (b >> 31) and (a >> 31) != (r >> 31)

    def op_lsl(self, args):
        dst, src0, src1 = self._3arg(args)
        r = self.regs[self.reg_numbers[src0]] << self._reg_or_literal(src1)
        self._dstpc(dst, r & 0xffffffff)

    def op_lsls(self, args):
        dst, src0, src1 = self._3arg(args)
        r = self.regs[self.reg_numbers[src0]] << self._reg_or_literal(src1)
        self.cpsrZ = r == 0
        self.cpsrN = (r >> 31) & 1
        self.cpsrC = (r >> 32) & 1
        self._dstpc(dst, r & 0xffffffff)

    def op_lsr(self, args):
        dst, src0, src1 = self._3arg(args)
        r = self.regs[self.reg_numbers[src0]] >> self._reg_or_literal(src1)
        self._dstpc(dst, r & 0xffffffff)

    def op_lsrs(self, args):
        dst, src0, src1 = self._3arg(args)
        r = self.regs[self.reg_numbers[src0]] >> self._reg_or_literal(src1)
        self.cpsrZ = r == 0
        self.cpsrN = (r >> 31) & 1
        self.cpsrC = (r >> 32) & 1
        self._dstpc(dst, r & 0xffffffff)

    def op_asr(self, args):
        dst, src0, src1 = self._3arg(args)
        r = self.regs[self.reg_numbers[src0]]
        if r & 0x80000000: r |= 0xffffffff00000000
        r = r >> self._reg_or_literal(src1)
        self._dstpc(dst, r & 0xffffffff)

    def op_asrs(self, args):
        dst, src0, src1 = self._3arg(args)
        r = self.regs[self.reg_numbers[src0]]
        if r & 0x80000000: r |= 0xffffffff00000000
        r = r >> self._reg_or_literal(src1)
        self.cpsrZ = r == 0
        self.cpsrN = (r >> 31) & 1
        self.cpsrC = (r >> 32) & 1
        self._dstpc(dst, r & 0xffffffff)

    def op_msr(self, args):
        """Stub"""
        dst, src = args.split(', ')

    def op_mrs(self, args):
        """Stub"""
        dst, src = args.split(', ')
        self.regs[self.reg_numbers[dst]] = 0x5d5d5d5d

