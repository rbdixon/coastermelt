```
                        __                             __ __   
.----.-----.---.-.-----|  |_.-----.----.--------.-----|  |  |_ 
|  __|  _  |  _  |__ --|   _|  -__|   _|        |  -__|  |   _|
|____|_____|___._|_____|____|_____|__| |__|__|__|_____|__|____|
--A fun way to break your Blu-Ray burner-----------------------
```

The **coastermelt** project is an effort to make open source firmware for creatively repurposing BD-R drives.

Still TOTALLY NOT REAL YET. Just a pie-in-the-sky reverse engineering effort. When details come along that I can publicize, they'll go here for now. Eventually this repo will become an open source firmware, I hope.


What it has
-----------

For the Samsung SE-506CB external Blu-Ray burner, it provides a way to install 'backdoored' firmware to support a set of programmatic and interactive reverse engineering tools.

Mac OS X only for now. Requires an ARM cross compiler (arm-none-eabi-gcc and friends) as well as a local compiler (XCode).

NOTE that there are NO copyrighted firmware images included here in this open source project! To be on the safe side, we don't include large disassemblies or reverse engineering databases either. This project includes tools written from scratch, notes based on guesswork and extensive experimentation. The installation process requires modifying an official (copyrighted) firmware image, which this project does not redistribute. The build system will automatically download this file from the official source.


Parts
-----

* backdoor - A firmware patch to provide a debugging backdoor, and interactive Python tools based on that backdoor.
* doc - Reverse engineering notes
* flasher - Command line tool to flash firmware, Python tool to patch checksums


~MeS`14
