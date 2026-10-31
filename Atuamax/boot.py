"""Identify the active F6201B bank from the U-Boot handoff in /proc/cmdline."""

import re


BOOT_MARKERS = {
    "0x1a20000": ("mtd7", 0),  # Both address layouts occur with N6 and N7 firmware.
    "0x3a20000": ("mtd8", 1),
    "0x1a00000": ("mtd7", 0),
    "0x3a00000": ("mtd8", 1),
}


def active_bank(cmdline: str) -> str:
    records = re.findall(
        r"\bU-Boot\s+V[0-9A-Za-z.]+\s+\d{14}\s+(0x[0-9a-f]+)\s+(0x[0-9a-f]+)\b",
        cmdline, flags=re.IGNORECASE,
    )
    if len(records) != 1:
        raise RuntimeError("Marcador de boot ausente ou ambíguo; nenhuma gravação será feita")
    marker, region_text = (value.lower() for value in records[0])
    found = BOOT_MARKERS.get(marker)
    if found is None or int(region_text, 16) != found[1]:
        raise RuntimeError(f"Marcador de boot desconhecido ou inconsistente: {marker} {region_text}")
    return found[0]
