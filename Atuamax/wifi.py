"""Set the two primary F6201B Wi-Fi names from the ONT's own MAC."""

import re
from pathlib import Path

from transport import TelnetSession, receive_file


ROWS = (0, 4)  # Primary 2.4 GHz and 5 GHz entries in the validated F6201B profile.


def name_from_mac(mac: bytes, prefix: str = "Atuamax") -> str:
    if len(mac) != 6:
        raise ValueError("MAC do equipamento inválido")
    if not prefix.isascii() or not prefix.isalnum() or len(prefix) > 16:
        raise ValueError("Prefixo Wi-Fi inválido")
    return prefix + "_" + mac.hex()[-4:].upper()


def verify_names(telnet: TelnetSession, name: str):
    output = telnet.run("iwconfig", timeout=25)
    for interface in ("wlan0", "wlan5"):
        if not re.search(rf"(?m)^{interface}\s+IEEE[^\r\n]*ESSID:\"{re.escape(name)}\"", output):
            raise RuntimeError(f"O nome da rede {interface} ainda não corresponde a {name}")


def _check_table(output: str):
    if '<Tbl name="WLANCfg" RowCount="10">' not in output:
        raise RuntimeError("Tabela Wi-Fi incompatível com o modelo validado")
    for row in ROWS:
        match = re.search(rf'<Row No="{row}">(.*?)(?=<Row No=|</Tbl>)', output, re.DOTALL)
        if not match or not re.search(r'<DM name="Enable" val="1"', match.group(1)):
            raise RuntimeError(f"A rede Wi-Fi principal da linha {row} não está ativa; nomes não alterados")


def _db_command(telnet: TelnetSession, command: str):
    output = telnet.run("sendcmd 1 DB " + command, timeout=35)
    body = output.split("\n", 1)[-1].split("__F6201B_EXIT__", 1)[0]
    if ("all:print all table" in body or
            re.search(r"(?i)\b(error|failed|invalid|unknown)\b", body) or
            re.search(r"IF_ERRORID[^0-9]*[1-9]", body)):
        raise RuntimeError("O banco de dados recusou: " + command.split()[0])


def apply_names(telnet: TelnetSession, mac: bytes, local_ip: str, router_ip: str,
                backup_dir: Path, log, prefix: str = "Atuamax") -> str:
    table = telnet.run("sendcmd 1 DB p WLANCfg")
    _check_table(table)
    name = name_from_mac(mac, prefix)
    remote_cfg = "/userconfig/cfg/db_user_cfg.xml"
    log("Salvando configuração atual antes de alterar os nomes Wi-Fi...")
    size_output = telnet.run("ls -l " + remote_cfg)
    match = re.search(r"(?m)^[-drlwxstST]{10}\s+\d+\s+\S+\s+\S+\s+(\d+)\s+", size_output)
    if not match:
        raise RuntimeError("Backup da configuração Wi-Fi não foi criado")
    size = int(match.group(1))
    if not 128 <= size <= 5_000_000:
        raise RuntimeError("Tamanho inesperado do backup da configuração")
    receive_file(telnet, local_ip, router_ip, remote_cfg, "db_user_cfg.xml",
                 backup_dir / "config_before_wifi.bin", size)
    for row in ROWS:
        _db_command(telnet, f"setdef WLANCfg {row} ESSID {name}")
        _db_command(telnet, f"set WLANCfg {row} ESSID {name}")
    _db_command(telnet, "save")
    log(f"Redes 2,4 e 5 GHz configuradas como {name}.")
    return name
