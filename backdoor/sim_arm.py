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

__all__ = [ 'simulate_arm' ]

import cStringIO, struct
from code import *
from dump import *


def simulate_arm(device):
    """Create a new ARM simulator, backed by the provided remote device
    Returns a SimARM object with regs[], memory, and step().
    """
    m = SimARMMemory(device)

    m.skip(0x04001000, "Reset control?")
    m.skip(0x04002088, "LED / Solenoid GPIOs, breaks bitbang backdoor")
    m.skip(0x04030f04, "Memory region control flags")
    m.skip(0x04030f20, "DRAM memory region, contains backdoor code")
    m.skip(0x04030f24, "DRAM memory region, contains backdoor code")
    m.skip(0x04030f40, "Stack memory region")
    m.skip(0x04030f44, "Stack memory region")
    
    # Stub out a loop during init that seems to be spinning with a register read inside (performance)
    m.patch(0x0007bc3c, 'nop; nop')

    # Stub out encrypted functions related to DRM. Hopefully we don't need to bother supporting them.
    m.patch(0x00011080, 'mov r0, #0; bx lr', thumb=False)

    # Try keeping some of the RAM local (performance)
    m.local_ram(0x1c00000, 0x1c1ffff)
    m.local_ram(0x1f57000, 0x1ffffff)
    m.local_ram(0x2000600, 0x2000fff)

    return SimARM(m)


class RunEncoder:
    """Find runs that write the same pattern to consecutive addresses.
    Both 'write' and 'flush' return a (count, address, pattern, size) tuple,
    where 'count' might be zero if no work needs to be done.
    """
    def __init__(self):
        self.count = 0
        self.key = (None, None, None)

    def write(self, address, pattern, size):
        if self.key == (address - self.count * size, pattern, size):
            self.count += 1
            return (0, None, None, None)
        else:
            r = self.flush()
            self.key = (address, pattern, size)
            self.count = 1
            return r

    def flush(self):
        r = (self.count,) + self.key
        self.count = 0
        self.key = (None, None, None)
        return r


class SimARMMemory:
    """Memory manager for a simulated ARM core, backed by a remote device.
    
    This manages a tiny bit of caching and write consolidation, to conserve
    bandwidth on the bitbang debug pipe.
    """
    def __init__(self, device, logfile=None):
        self.device = device
        self.logfile = logfile

        # Instruction cache
        self.instructions = {}

        # Special addresses
        self.skip_stores = {}
        self.patch_notes = {}

        # Local RAM and cached flash, reads and writes don't go to hardware
        self.local_addresses = {}
        self.local_data = cStringIO.StringIO()

        # Detect fills
        self.rle = RunEncoder()

    def skip(self, address, reason):
        self.skip_stores[address] = reason

    def patch(self, address, code, thumb = True):
        # Note the extra nop to facilitate the way load_assembly sizes instructions
        s = assemble_string(address, code + '\nnop', thumb=thumb)
        lines = disassembly_lines(disassemble_string(s, address=address, thumb=thumb))
        self._load_assembly(address, lines, thumb=thumb)
        for l in lines[:1]:
            self.patch_notes[l.address] = True

    def local_ram(self, begin, end):
        i = begin
        while i <= end:
            self.local_addresses[i] = True
            i += 1

    def note(self, address):
        if self.patch_notes.get(address):
            return 'PATCH'
        return ''

    def log_store(self, address, data, size='word', message=''):
        if self.logfile:
            self.logfile.write("arm-mem-STORE %4s[%08x] <- %08x %s\n" % (size, address, data, message))

    def log_fill(self, address, pattern, count, size='word'):
        if self.logfile:
            self.logfile.write("arm-mem-FILL  %4s[%08x] <- %08x * %04x\n" % (size, address, pattern, count))

    def log_load(self, address, data, size='word'):
        if self.logfile:
            self.logfile.write("arm-mem-LOAD  %4s[%08x] -> %08x\n" % (size, address, data))

    def log_prefetch(self, address):
        if self.logfile:
            self.logfile.write("arm-prefetch [%08x]\n" % address)

    def check_address(self, address):
        # Called before write (crash less) and after read (curiosity)
        if address >= 0x05000000:
            raise IndexError("Address %08x doesn't look valid. Simulator bug?" % address)

    def post_rle_store(self, count, address, pattern, size):
        """Process stores after RLE consolidation has happened"""

        if count > 1 and size == 4:
            self.check_address(address)
            self.log_fill(address, pattern, count)
            self.device.fill_words(address, pattern, count)
            return

        if count > 1 and size == 1:
            self.check_address(address)
            self.log_fill(address, pattern, count, 'byte')
            self.device.fill_bytes(address, pattern, count)
            return

        while count > 0:
            self.check_address(address)

            if size == 4:
                self.log_store(address, pattern)
                self.device.poke(address, pattern)

            elif size == 2:
                self.log_store(address, data, 'half')
                self.device.poke_byte(address, data & 0xff)
                self.device.poke_byte(address + 1, data >> 8)

            else:
                assert size == 1
                self.log_store(address, pattern, 'byte')
                self.device.poke_byte(address, pattern)

            count -= 1
            address += size

    def flush(self):
        # If there's a cached fill, make it happen
        self.post_rle_store(*self.rle.flush())

    def flash_prefetch(self, address, size, max_round_trips = None):
        self.log_prefetch(address)
        block = read_block(self.device, address, size, max_round_trips=max_round_trips)
        self.local_ram(address, address + len(block) - 1)
        self.local_data.seek(address)
        self.local_data.write(block)

    def flash_prefetch_hint(self, address):
        """We're accessing an address, if it's flash maybe prefetch around it"""
        # Flash prefetch, whatever we can get in one packet
        if address < 0x200000 and address not in self.local_addresses:
            self.flush()
            self.flash_prefetch(address, size=0x100, max_round_trips=1)        

    def load(self, address):
        self.flash_prefetch_hint(address)
        if address in self.local_addresses:
            self.local_data.seek(address)
            return struct.unpack('<I', self.local_data.read(4))[0]

        # Non-cached device address
        self.flush()
        data = self.device.peek(address)
        self.log_load(address, data)
        self.check_address(address)
        return data

    def load_half(self, address):
        self.flash_prefetch_hint(address)
        if address in self.local_addresses:
            self.local_data.seek(address)
            return struct.unpack('<H', self.local_data.read(2))[0]

        # Doesn't seem to be architecturally necessary; emulate with bytes
        self.flush()
        data = self.device.peek_byte(address) | (self.device.peek_byte(address + 1) << 8)
        self.log_load(address, data, 'half')
        self.check_address(address)
        return data

    def load_byte(self, address):
        self.flash_prefetch_hint(address)
        if address in self.local_addresses:
            self.local_data.seek(address)
            return ord(self.local_data.read(1))

        self.flush()
        data = self.device.peek_byte(address)
        self.log_load(address, data, 'byte')
        self.check_address(address)
        return data

    def store(self, address, data):
        if address in self.local_addresses:
            self.local_data.seek(address)
            self.local_data.write(struct.pack('<I', data))
            return

        if address in self.skip_stores:
            self.log_store(address, data,
                message='(skipped: %s)'% self.skip_stores[address])
            return

        self.post_rle_store(*self.rle.write(address, data, 4))

    def store_half(self, address, data):
        if address in self.local_addresses:
            self.local_data.seek(address)
            self.local_data.write(struct.pack('<H', data))
            return

        if address in self.skip_stores:
            self.log_store(address, data,
                message='(skipped: %s)'% self.skip_stores[address])
            return

        self.post_rle_store(*self.rle.write(address, data, 2))

    def store_byte(self, address, data):
        if address in self.local_addresses:
            self.local_data.seek(address)
            self.local_data.write(chr(data))
            return

        if address in self.skip_stores:
            self.log_store(address, data,
                message='(skipped: %s)'% self.skip_stores[address])
            return

        self.post_rle_store(*self.rle.write(address, data, 1))

    def fetch(self, address, thumb):
        try:
            return self.instructions[thumb | (address & ~1)]
        except KeyError:
            self.check_address(address)
            self._load_instruction(address, thumb)
            return self.instructions[thumb | (address & ~1)]

    def _load_instruction(self, address, thumb, fetch_size = 32):
        lines = disassembly_lines(disassemble(self.device, address, fetch_size, thumb=thumb))
        self._load_assembly(address, lines, thumb=thumb)

    def _load_assembly(self, address, lines, thumb):
        for i in range(len(lines) - 1):
            lines[i].next_address = lines[i+1].address
            addr = thumb | (lines[i].address & ~1)
            if addr not in self.instructions:
                self.instructions[addr] = lines[i]


class SimARM:
    """Main simulator class for the ARM subset we support in %sim

    Registers are available at regs[], call step() to single-step. Uses the
    provided memory manager object to handle load(), store(), and fetch().
    """
    def __init__(self, memory):
        self.memory = memory
        self.reset(0)

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
            for mode in ('', 'ia', 'ib', 'da', 'db', 'fd', 'fa', 'ed', 'ea'):
                self._generate_ldstm(memop, mode)

        # Initialize condition codes
        for name in self.__class__.__dict__.keys():
            if name.startswith('op_'):
                self._generate_condition_codes(getattr(self, name), name + '%s')

        # Near branches
        self.__dict__['op_b.n'] = self.op_b
        self._generate_condition_codes(self.op_b, 'op_b%s.n')

    def reset(self, vector):
        self.regs = [0] * 16
        self.thumb = vector & 1
        self.cpsrV = False
        self.cpsrC = False
        self.cpsrZ = False
        self.cpsrN = False
        self.regs[15] = vector & 0xfffffffe
        self.lr = 0xffffffff
        self.step_count = 0

    def step(self):
        """Step the simulated ARM by one instruction"""
        self.step_count += 1
        regs = self.regs
        instr = self.memory.fetch(regs[15], self.thumb)
        self._branch = None

        if self.thumb:
            regs[15] = (instr.next_address + 3) & ~3
        else:
            regs[15] += 8

        try:
            getattr(self, 'op_' + instr.op)(instr)
            regs[15] = self._branch or instr.next_address
        except:
            regs[15] = instr.address
            raise

    def get_next_instruction(self):
        return self.memory.fetch(self.regs[15], self.thumb)

    def flags_string(self):
        return ''.join([
            '-N'[self.cpsrN],
            '-Z'[self.cpsrZ],
            '-C'[self.cpsrC],
            '-V'[self.cpsrV],
            '-T'[self.thumb],
        ])       

    def summary_line(self):
        up_next = self.get_next_instruction()
        return "%s %s >%08x %5s %-8s %s" % (
            str(self.step_count).rjust(8, '.'),
            self.flags_string(),
            up_next.address,
            self.memory.note(up_next.address),
            up_next.op,
            up_next.args)

    def register_trace(self):
        parts = []
        for y in range(4):
            for x in range(4):
                i = y + x*4
                parts.append('%4s=%08x' % (self.reg_names[i], self.regs[i]))
            parts.append('\n')
        return ''.join(parts)

    def register_trace_line(self, count=15):
        return ' '.join('%s=%08x' % (self.reg_names[i], self.regs[i]) for i in range(count))

    def copy_registers_from(self, ns):
        self.regs = [ns.get(n, 0) for n in self.reg_names]

    def copy_registers_to(self, ns):
        for i, name in enumerate(self.reg_names):
            ns[name] = self.regs[i]

    def _generate_ldstm(self, memop, mode):
        impl = mode or 'ia'

        # Stack mnemonics
        if memop == 'st' and mode =='fd': impl = 'db'
        if memop == 'st' and mode =='fa': impl = 'ib'
        if memop == 'st' and mode =='ed': impl = 'da'
        if memop == 'st' and mode =='ea': impl = 'ia'
        if memop == 'ld' and mode =='fd': impl = 'ia'
        if memop == 'ld' and mode =='fa': impl = 'da'
        if memop == 'ld' and mode =='ed': impl = 'ib'
        if memop == 'ld' and mode =='ea': impl = 'db'

        def fn(i):
            left, right = i.args.split(', ', 1)
            assert right[0] == '{'
            writeback = left.endswith('!')
            left = self.reg_numbers[left.strip('!')]
            addr = self.regs[left]            
    
            for r in right.strip('{}').split(', '):
                if impl == 'ib': addr += 4
                if impl == 'db': addr -= 4
                if memop == 'st':
                    self.memory.store(addr, self.regs[self.reg_numbers[r]])
                else:
                    self._dstpc(r, self.memory.load(addr))
                if impl == 'ia': addr += 4
                if impl == 'da': addr -= 4
    
            if writeback:
                self.regs[left] = addr

        setattr(self, 'op_' + memop + 'm' + mode, fn)
        self._generate_condition_codes(fn, 'op_' + memop + 'm%s' + mode)
        self._generate_condition_codes(fn, 'op_' + memop + 'm' + mode + '%s')

    def _generate_condition_codes(self, fn, name):
        setattr(self, name % 'eq', lambda i, fn=fn: (self.cpsrZ     ) and fn(i))
        setattr(self, name % 'ne', lambda i, fn=fn: (not self.cpsrZ ) and fn(i))
        setattr(self, name % 'cs', lambda i, fn=fn: (self.cpsrC     ) and fn(i))
        setattr(self, name % 'hs', lambda i, fn=fn: (self.cpsrC     ) and fn(i))
        setattr(self, name % 'cc', lambda i, fn=fn: (not self.cpsrC ) and fn(i))
        setattr(self, name % 'lo', lambda i, fn=fn: (not self.cpsrC ) and fn(i))
        setattr(self, name % 'mi', lambda i, fn=fn: (self.cpsrN     ) and fn(i))
        setattr(self, name % 'pl', lambda i, fn=fn: (not self.cpsrN ) and fn(i))
        setattr(self, name % 'vs', lambda i, fn=fn: (self.cpsrV     ) and fn(i))
        setattr(self, name % 'vc', lambda i, fn=fn: (not self.cpsrV ) and fn(i))
        setattr(self, name % 'hi', lambda i, fn=fn: (self.cpsrC and not self.cpsrZ ) and fn(i))
        setattr(self, name % 'ls', lambda i, fn=fn: (self.cpsrZ and not self.cpsrC ) and fn(i))
        setattr(self, name % 'ge', lambda i, fn=fn: (((not not self.cpsrN) == (not not self.cpsrV)) ) and fn(i))
        setattr(self, name % 'lt', lambda i, fn=fn: (((not not self.cpsrN) != (not not self.cpsrV)) ) and fn(i))
        setattr(self, name % 'gt', lambda i, fn=fn: (((not not self.cpsrN) == (not not self.cpsrV)) and not self.cpsrZ ) and fn(i))
        setattr(self, name % 'le', lambda i, fn=fn: (((not not self.cpsrN) != (not not self.cpsrV)) or self.cpsrZ      ) and fn(i))
        setattr(self, name % 'al', fn)

    def _reg_or_literal(self, s):
        if s[0] == '#':
            return int(s[1:], 0) & 0xffffffff
        return self.regs[self.reg_numbers[s]]

    def _shifter(self, s):
        # Returns (result, carry)
        l = s.split(', ', 1)
        if len(l) == 2:
            op, arg = l[1].split(' ')
            assert arg[0] == '#'
            if op == 'lsl':
                r = self._reg_or_literal(l[0]) << (int(arg[1:], 0) & 0xffffffff)
                c = r >> 32
            elif op == 'lsr':
                r = self._reg_or_literal(l[0]) >> (int(arg[1:], 0) & 0xffffffff)
                c = r >> 32
            if op == 'asr':
                r = self._reg_or_literal(l[0])
                if r & 0x80000000: r |= 0xffffffff00000000
                s = int(arg[1:], 0) & 0xffffffff
                r = r >> s
                c = r >> (s-1)
            return (r & 0xffffffff, c & 1)
        return (self._reg_or_literal(s), 0)

    def _reg_or_target(self, s):
        if s in self.reg_numbers:
            return self.regs[self.reg_numbers[s]]
        else:
            return int(s, 0)

    def _reladdr(self, right):
        assert right[0] == '['
        if right[-1] == ']':
            # [a, b]
            addrs = right.strip('[]').split(', ')
            v = self.regs[self.reg_numbers[addrs[0]]]
            if len(addrs) > 1:
                v = (v + self._reg_or_literal(addrs[1])) & 0xffffffff
            return v
        else:
            # [a], b
            addrs = right.split(', ')
            v = self.regs[self.reg_numbers[addrs[0].strip('[]')]]
            return (v + self._reg_or_literal(addrs[1])) & 0xffffffff

    @staticmethod
    def _3arg(i):
        l = i.args.split(', ', 2)
        if len(l) == 3:
            return l
        else:
            return [l[0]] + l

    def _dstpc(self, dst, r):
        if dst == 'pc':
            self._branch = r & ~1
            self.thumb = r & 1
        else:
            self.regs[self.reg_numbers[dst]] = r

    def op_ldr(self, i):
        left, right = i.args.split(', ', 1)
        self._dstpc(left, self.memory.load(self._reladdr(right)))

    def op_ldrh(self, i):
        left, right = i.args.split(', ', 1)
        self._dstpc(left, self.memory.load_half(self._reladdr(right)))

    def op_ldrb(self, i):
        left, right = i.args.split(', ', 1)
        self._dstpc(left, self.memory.load_byte(self._reladdr(right)))

    def op_str(self, i):
        left, right = i.args.split(', ', 1)
        self.memory.store(self._reladdr(right), self.regs[self.reg_numbers[left]])

    def op_strh(self, i):
        left, right = i.args.split(', ', 1)
        self.memory.store_half(self._reladdr(right), 0xffff & self.regs[self.reg_numbers[left]])

    def op_strb(self, i):
        left, right = i.args.split(', ', 1)
        self.memory.store_byte(self._reladdr(right), 0xff & self.regs[self.reg_numbers[left]])

    def op_push(self, i):
        reglist = i.args.strip('{}').split(', ')
        sp = self.regs[13] - 4 * len(reglist)
        self.regs[13] = sp
        for i in range(len(reglist)):
            self.memory.store(sp + 4 * i, self.regs[self.reg_numbers[reglist[i]]])

    def op_pop(self, i):
        reglist = i.args.strip('{}').split(', ')
        sp = self.regs[13]
        for i in range(len(reglist)):
            self._dstpc(reglist[i], self.memory.load(sp + 4 * i))
        self.regs[13] = sp + 4 * len(reglist)

    def op_bx(self, i):
        if i.args in self.reg_numbers:
            r = self.regs[self.reg_numbers[i.args]]
            self._branch = r & ~1
            self.thumb = r & 1
        else:
            r = int(i.args, 0)
            self._branch = r & ~1
            self.thumb = not self.thumb

    def op_bl(self, i):
        self.regs[14] = i.next_address | self.thumb
        self._branch = self._reg_or_target(i.args)

    def op_blx(self, i):
        self.regs[14] = i.next_address | self.thumb
        if i.args in self.reg_numbers:
            r = self.regs[self.reg_numbers[i.args]]
            self._branch = r & 0xfffffffe
            self.thumb = r & 1
        else:
            r = int(i.args, 0)
            self._branch = r & 0xfffffffe
            self.thumb = not self.thumb

    def op_b(self, i):
        self._branch = int(i.args, 0)

    def op_nop(self, i):
        pass

    def op_mov(self, i):
        dst, src = i.args.split(', ', 1)
        s, _ = self._shifter(src)
        self._dstpc(dst, s)

    def op_movs(self, i):
        dst, src = i.args.split(', ', 1)
        r, self.cpsrC = self._shifter(src)
        self.cpsrZ = r == 0
        self.cpsrN = (r >> 31) & 1
        self._dstpc(dst, r)

    def op_mvn(self, i):
        dst, src = i.args.split(', ', 1)
        r, _ = self._shifter(src)
        self._dstpc(dst, r ^ 0xffffffff)

    def op_mvns(self, i):
        dst, src = i.args.split(', ', 1)
        r, self.csprC = self._shifter(src)
        r = r ^ 0xffffffff
        self.cpsrZ = r == 0
        self.cpsrN = (r >> 31) & 1
        self._dstpc(dst, r)

    def op_bic(self, i):
        dst, src0, src1 = self._3arg(i)
        s, _ = self._shifter(src1)
        r = self.regs[self.reg_numbers[src0]] & ~s
        self._dstpc(dst, r)

    def op_bics(self, i):
        dst, src0, src1 = self._3arg(i)
        s, _ = self._shifter(src1)
        r = self.regs[self.reg_numbers[src0]] & ~s
        self.cpsrZ = r == 0
        self.cpsrN = (r >> 31) & 1
        self._dstpc(dst, r)

    def op_orr(self, i):
        dst, src0, src1 = self._3arg(i)
        s, _ = self._shifter(src1)
        r = self.regs[self.reg_numbers[src0]] | s
        self._dstpc(dst, r)

    def op_orrs(self, i):
        dst, src0, src1 = self._3arg(i)
        s, self.cpsrC = self._shifter(src1)
        r = self.regs[self.reg_numbers[src0]] | s
        self.cpsrZ = r == 0
        self.cpsrN = (r >> 31) & 1
        self._dstpc(dst, r)

    def op_and(self, i):
        dst, src0, src1 = self._3arg(i)
        s, _ = self._shifter(src1)
        r = self.regs[self.reg_numbers[src0]] & s
        self._dstpc(dst, r)

    def op_ands(self, i):
        dst, src0, src1 = self._3arg(i)
        s, self.cpsrC = self._shifter(src1)
        r = self.regs[self.reg_numbers[src0]] & s
        self.cpsrZ = r == 0
        self.cpsrN = (r >> 31) & 1
        self._dstpc(dst, r)

    def op_tst(self, i):
        dst, src0, src1 = self._3arg(i)
        s, self.cpsrC = self._shifter(src1)
        r = self.regs[self.reg_numbers[src0]] & s
        self.cpsrZ = r == 0
        self.cpsrN = (r >> 31) & 1

    def op_eor(self, i):
        dst, src0, src1 = self._3arg(i)
        s, _ = self._shifter(src1)
        r = self.regs[self.reg_numbers[src0]] ^ s
        self._dstpc(dst, r)

    def op_eors(self, i):
        dst, src0, src1 = self._3arg(i)
        s, self.cpsrC = self._shifter(src1)
        r = self.regs[self.reg_numbers[src0]] ^ s
        self.cpsrZ = r == 0
        self.cpsrN = (r >> 31) & 1
        self._dstpc(dst, r)
        
    def op_add(self, i):
        dst, src0, src1 = self._3arg(i)
        s, _ = self._shifter(src1)
        r = self.regs[self.reg_numbers[src0]] + s
        self._dstpc(dst, r & 0xffffffff)

    def op_adds(self, i):
        dst, src0, src1 = self._3arg(i)
        a = self.regs[self.reg_numbers[src0]]
        b, _ = self._shifter(src1)
        r = a + b
        self.cpsrN = (r >> 31) & 1
        self.cpsrZ = not (r & 0xffffffff)
        self.cpsrC = r > 0xffffffff
        self.cpsrV = ((a >> 31) & 1) == ((b >> 31) & 1) and ((a >> 31) & 1) != ((r >> 31) & 1) and ((b >> 31) & 1) != ((r >> 31) & 1)
        self._dstpc(dst, r & 0xffffffff)

    def op_adc(self, i):
        dst, src0, src1 = self._3arg(i)
        s, _ = self._shifter(src1)
        r = self.regs[self.reg_numbers[src0]] + s + (self.cpsrC & 1)
        self._dstpc(dst, r & 0xffffffff)

    def op_adcs(self, i):
        dst, src0, src1 = self._3arg(i)
        a = self.regs[self.reg_numbers[src0]]
        b, _ = self._shifter(src1)
        r = a + b + (self.cpsrC & 1)
        self.cpsrN = (r >> 31) & 1
        self.cpsrZ = not (r & 0xffffffff)
        self.cpsrC = r > 0xffffffff
        self.cpsrV = ((a >> 31) & 1) == ((b >> 31) & 1) and ((a >> 31) & 1) != ((r >> 31) & 1) and ((b >> 31) & 1) != ((r >> 31) & 1)
        self._dstpc(dst, r & 0xffffffff)

    def op_sub(self, i):
        dst, src0, src1 = self._3arg(i)
        s, _ = self._shifter(src1)
        r = self.regs[self.reg_numbers[src0]] - s
        self._dstpc(dst, r & 0xffffffff)

    def op_subs(self, i):
        dst, src0, src1 = self._3arg(i)
        a = self.regs[self.reg_numbers[src0]]
        b, _ = self._shifter(src1)
        r = a - b
        self.cpsrN = (r >> 31) & 1
        self.cpsrZ = not (r & 0xffffffff)
        self.cpsrC = (a & 0xffffffff) >= (b & 0xffffffff)
        self.cpsrV = ((a >> 31) & 1) != ((b >> 31) & 1) and ((a >> 31) & 1) != ((r >> 31) & 1)
        self._dstpc(dst, r & 0xffffffff)

    def op_rsb(self, i):
        dst, src0, src1 = self._3arg(i)
        s, _ = self._shifter(src1)
        r = s - self.regs[self.reg_numbers[src0]]
        self._dstpc(dst, r & 0xffffffff)

    def op_rsbs(self, i):
        dst, src0, src1 = self._3arg(i)
        b = self.regs[self.reg_numbers[src0]]
        a, _ = self._shifter(src1)
        r = a - b
        self.cpsrN = (r >> 31) & 1
        self.cpsrZ = not (r & 0xffffffff)
        self.cpsrC = (a & 0xffffffff) >= (b & 0xffffffff)
        self.cpsrV = ((a >> 31) & 1) != ((b >> 31) & 1) and ((a >> 31) & 1) != ((r >> 31) & 1)
        self._dstpc(dst, r & 0xffffffff)

    def op_cmp(self, i):
        dst, src0, src1 = self._3arg(i)
        a = self.regs[self.reg_numbers[src0]]
        b, _ = self._shifter(src1)
        r = a - b
        self.cpsrN = (r >> 31) & 1
        self.cpsrZ = not (r & 0xffffffff)
        self.cpsrC = (a & 0xffffffff) >= (b & 0xffffffff)
        self.cpsrV = ((a >> 31) & 1) != ((b >> 31) & 1) and ((a >> 31) & 1) != ((r >> 31) & 1)

    def op_lsl(self, i):
        dst, src0, src1 = self._3arg(i)
        r = self.regs[self.reg_numbers[src0]] << self._reg_or_literal(src1)
        self._dstpc(dst, r & 0xffffffff)

    def op_lsls(self, i):
        dst, src0, src1 = self._3arg(i)
        r = self.regs[self.reg_numbers[src0]] << self._reg_or_literal(src1)
        self.cpsrZ = not (r & 0xffffffff)
        self.cpsrN = (r >> 31) & 1
        self.cpsrC = (r >> 32) & 1
        self._dstpc(dst, r & 0xffffffff)

    def op_lsr(self, i):
        dst, src0, src1 = self._3arg(i)
        r = self.regs[self.reg_numbers[src0]] >> self._reg_or_literal(src1)
        self._dstpc(dst, r & 0xffffffff)

    def op_lsrs(self, i):
        dst, src0, src1 = self._3arg(i)
        r = self.regs[self.reg_numbers[src0]] >> self._reg_or_literal(src1)
        self.cpsrZ = not (r & 0xffffffff)
        self.cpsrN = (r >> 31) & 1
        self.cpsrC = (r >> 32) & 1
        self._dstpc(dst, r & 0xffffffff)

    def op_asr(self, i):
        dst, src0, src1 = self._3arg(i)
        r = self.regs[self.reg_numbers[src0]]
        if r & 0x80000000: r |= 0xffffffff00000000
        r = r >> self._reg_or_literal(src1)
        self._dstpc(dst, r & 0xffffffff)

    def op_asrs(self, i):
        dst, src0, src1 = self._3arg(i)
        r = self.regs[self.reg_numbers[src0]]
        if r & 0x80000000: r |= 0xffffffff00000000
        r = r >> self._reg_or_literal(src1)
        self.cpsrZ = not (r & 0xffffffff)
        self.cpsrN = (r >> 31) & 1
        self.cpsrC = (r >> 32) & 1
        self._dstpc(dst, r & 0xffffffff)

    def op_mul(self, i):
        dst, src0, src1 = self._3arg(i)
        a = self.regs[self.reg_numbers[src0]]
        b, _ = self._shifter(src1)
        r = a * b
        self.cpsrN = (r >> 31) & 1
        self.cpsrZ = not (r & 0xffffffff)
        self._dstpc(dst, r & 0xffffffff)

    def op_muls(self, i):
        dst, src0, src1 = self._3arg(i)
        a = self.regs[self.reg_numbers[src0]]
        b, _ = self._shifter(src1)
        r = a * b
        self._dstpc(dst, r & 0xffffffff)

    def op_msr(self, i):
        """Stub"""
        dst, src = i.args.split(', ')

    def op_mrs(self, i):
        """Stub"""
        dst, src = i.args.split(', ')
        self.regs[self.reg_numbers[dst]] = 0x5d5d5d5d

    def op_clz(self, i):
        dst, src = i.args.split(', ', 1)
        r, _ = self._shifter(src)
        i = 0
        while i < 32:
            if r & (1 << i):
                break
            else:
                i += 1
        self._dstpc(dst, i)

