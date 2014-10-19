# This module becomes the user_ns for our IPython shell

import struct, sys, os, re

import shell_functions
from shell_functions import *

import shell_magics
from shell_magics import *

import dump
from dump import *

import code
from code import *

import mem
from mem import *

from watch import *
from console import *
from hilbert import hilbert

import IPython
import IPython.terminal.embed

import binascii
from binascii import a2b_hex, b2a_hex

import random
from random import randint

# Shell variables for default_hook()
hook_stack_lines = 8
hook_show_stack = True
hook_show_registers = True
hook_show_timestamp = True
hook_show_message = True
