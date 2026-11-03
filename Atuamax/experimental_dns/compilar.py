"""Rebuild both ARM soft-float binaries with Zig 0.13.0.

Usage: python compilar.py C:/tools/zig.exe
"""

from pathlib import Path
import subprocess
import sys
import tarfile

HERE = Path(__file__).resolve().parent
ARCHIVE = HERE / "upstream/dnsmasq-2.91.tar.gz"
SOURCE = HERE / "upstream/dnsmasq-2.91/src"
ZIG = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("zig")
OBJECTS = HERE / "objetos_build"
OBJECTS.mkdir(exist_ok=True)
if not SOURCE.is_dir():
    with tarfile.open(ARCHIVE, "r:gz") as tar:
        tar.extractall(HERE / "upstream", filter="data")

sources = [
    "cache", "rfc1035", "util", "option", "forward", "network", "dnsmasq",
    "dhcp", "lease", "rfc2131", "netlink", "dbus", "bpf", "helper", "tftp",
    "log", "conntrack", "dhcp6", "rfc3315", "dhcp-common", "outpacket",
    "radv", "slaac", "auth", "ipset", "pattern", "domain", "dnssec",
    "blockdata", "tables", "loop", "inotify", "poll", "rrfilter", "edns0",
    "arp", "crypto", "dump", "ubus", "metrics", "domain-match", "nftset",
]
target = ["-target", "arm-linux-musleabi", "-mcpu=arm926ej_s"]
flags = ["-Os", "-D_GNU_SOURCE", '-DVERSION="2.91"',
         "-DNO_DHCP", "-DNO_DHCP6", "-DNO_TFTP", "-DNO_SCRIPT", "-DNO_AUTH",
         "-DNO_LOOP", "-DNO_INOTIFY", "-DNO_ID", "-DNO_IPSET"]
objects = []
for name in sources:
    obj = OBJECTS / f"{name}.o"
    subprocess.run([str(ZIG), "cc", *target, *flags, "-c",
                    str(SOURCE / f"{name}.c"), "-o", str(obj)], check=True)
    objects.append(str(obj))
subprocess.run([str(ZIG), "cc", *target, "-static", "-Os", *objects,
                "-o", str(HERE / "dnsmasq-arm-softfloat")], check=True)
subprocess.run([str(ZIG), "cc", *target, "-static", "-Os",
                str(HERE / "server.c"), "-o", str(HERE / "dnsweb-arm")], check=True)
print("Binários ARM reconstruídos.")
