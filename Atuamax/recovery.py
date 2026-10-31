"""Restore the stock web UI in both validated F6201B firmware banks."""

from datetime import datetime
from hashlib import sha256
import ipaddress
import json
from pathlib import Path
import re
import struct
import time

import requests

from factory_auth import BoundAdapter, discover_router, open_telnet
from boot import active_bank
from theme import APP, FILE_ORDER, REQUIRED_FILE_ORDER, jffs_crc, load_profile, make_inode
from transport import TelnetSession, receive_file, send_file


STOCK_PATHS = {
    "login.css": "/css/login.css",
    "template.css": "/css/template.css",
    "commonpage.css": "/css/commonpage.css",
    "home.css": "/css/home.css",
    "Logo_ZTE.png": "/img/Logo_ZTE.png",
}


def load_stock_files(profile: dict) -> dict[str, bytes]:
    folder = APP / profile["stock_resource_dir"]
    result = {name: (folder / name).read_bytes() for name in FILE_ORDER}
    for name, data in result.items():
        if sha256(data).hexdigest() != profile["stock_resource_sha256"][name]:
            raise RuntimeError(f"Arquivo original de recuperação alterado: {name}")
    return result


def parse_overlay(block: bytes, profile: dict) -> tuple[dict[int, int], int]:
    """Validate every JFFS2 node in the reserved block and find its next free page."""
    if len(block) != profile["block_size"]:
        raise RuntimeError("Tamanho do bloco de interface inesperado")
    allowed = {entry["ino"] for entry in profile["inodes"].values()}
    versions: dict[int, int] = {}
    cursor = 0
    last_end = 0
    while cursor < len(block):
        if block[cursor:cursor + 4] == b"\xff" * 4:
            cursor += 4
            continue
        if cursor + 68 > len(block):
            raise RuntimeError("Bloco de interface termina em um nó incompleto")
        magic, node_type, total = struct.unpack_from("<HHI", block, cursor)
        if (magic, node_type) != (0x1985, 0xE002) or total < 68 or cursor + total > len(block):
            raise RuntimeError(f"Conteúdo desconhecido no bloco de interface, posição {cursor}")
        node = block[cursor:cursor + 68]
        if (struct.unpack_from("<I", node, 8)[0] != jffs_crc(node[:8]) or
                struct.unpack_from("<I", node, 64)[0] != jffs_crc(node[:60])):
            raise RuntimeError("Cabeçalho da interface com CRC inválido")
        ino, version = struct.unpack_from("<II", node, 12)
        data_size = struct.unpack_from("<I", node, 48)[0]
        if ino not in allowed or 68 + data_size != total:
            raise RuntimeError("O bloco contém arquivos fora do tema conhecido")
        data = block[cursor + 68:cursor + total]
        if struct.unpack_from("<I", node, 60)[0] != jffs_crc(data):
            raise RuntimeError("Arquivo da interface com CRC inválido")
        versions[ino] = max(version, versions.get(ino, 0))
        last_end = cursor + (total + 3) // 4 * 4
        cursor = last_end
    for name in REQUIRED_FILE_ORDER:
        meta = profile["inodes"][name]
        if versions and versions.get(meta["ino"], 0) <= meta["highest_version"]:
            raise RuntimeError(f"Arquivo {name} ausente da personalização")
    page = profile["page_size"]
    free = (last_end + page - 1) // page * page
    if block[free:] != b"\xff" * (len(block) - free):
        raise RuntimeError("Não há espaço livre contínuo para restaurar a interface")
    return versions, free


def overlay_files(block: bytes, profile: dict) -> dict[str, bytes]:
    """Reconstruct the latest files from a validated UI block."""
    versions, _ = parse_overlay(block, profile)
    if not versions:
        return {}
    pieces: dict[int, list[tuple[int, int, int, bytes]]] = {ino: [] for ino in versions}
    cursor = 0
    while cursor < len(block):
        if block[cursor:cursor + 4] == b"\xff" * 4:
            cursor += 4
            continue
        total = struct.unpack_from("<I", block, cursor + 4)[0]
        ino, version = struct.unpack_from("<II", block, cursor + 12)
        size = struct.unpack_from("<I", block, cursor + 28)[0]
        offset = struct.unpack_from("<I", block, cursor + 44)[0]
        data_size = struct.unpack_from("<I", block, cursor + 48)[0]
        pieces[ino].append((version, size, offset, block[cursor + 68:cursor + 68 + data_size]))
        cursor += (total + 3) // 4 * 4
    files = {}
    for name in FILE_ORDER:
        ino = profile["inodes"][name]["ino"]
        if ino not in pieces:
            continue
        data = bytearray()
        latest_size = 0
        for version, size, offset, fragment in sorted(pieces[ino]):
            end = offset + len(fragment)
            if len(data) < end:
                data.extend(b"\x00" * (end - len(data)))
            data[offset:end] = fragment
            latest_size = size
        files[name] = bytes(data[:latest_size])
    return files


def _fresh_stock_payload(profile: dict, stock: dict[str, bytes],
                         versions: dict[int, int]) -> tuple[int, bytes, bytes]:
    nodes = []
    chunk = profile["chunk_size"]
    for name in FILE_ORDER:
        meta = profile["inodes"][name]
        if meta["ino"] not in versions:
            continue
        content = stock[name]
        base = max(meta["highest_version"], versions.get(meta["ino"], 0))
        for index, offset in enumerate(range(0, len(content), chunk), 1):
            nodes.append(make_inode(bytes.fromhex(meta["header_hex"]), meta["ino"],
                                    base + index, len(content), offset,
                                    content[offset:offset + chunk]))
    raw = b"".join(nodes)
    page = profile["page_size"]
    payload = raw + b"\xff" * (-len(raw) % page)
    if len(payload) > profile["block_size"]:
        raise RuntimeError("A interface original não cabe em um bloco livre")
    expected = payload + b"\xff" * (profile["block_size"] - len(payload))
    return 0, payload, expected


def build_restore_payload(block: bytes, profile: dict, stock: dict[str, bytes]) -> tuple[int, bytes, bytes]:
    versions, start = parse_overlay(block, profile)
    if not versions:
        return start, b"", block
    nodes = []
    chunk = profile["chunk_size"]
    for name in FILE_ORDER:
        meta = profile["inodes"][name]
        if meta["ino"] not in versions:
            continue
        content = stock[name]
        for index, offset in enumerate(range(0, len(content), chunk), 1):
            nodes.append(make_inode(bytes.fromhex(meta["header_hex"]), meta["ino"],
                                    versions[meta["ino"]] + index, len(content), offset,
                                    content[offset:offset + chunk]))
    raw = b"".join(nodes)
    page = profile["page_size"]
    payload = raw + b"\xff" * (-len(raw) % page)
    if start + len(payload) > len(block):
        raise RuntimeError("A interface original não cabe no bloco disponível")
    expected = block[:start] + payload + block[start + len(payload):]
    return start, payload, expected


def verify_stock_web(ip: str, stock: dict[str, bytes], source_ip: str | None = None) -> tuple[bool, str]:
    try:
        with requests.Session() as session:
            session.trust_env = False
            if source_ip:
                session.mount("http://", BoundAdapter(source_ip))
            for name, path in STOCK_PATHS.items():
                response = session.get(f"http://{ip}{path}", params={"t": time.time_ns()}, timeout=5)
                response.raise_for_status()
                if response.content != stock[name]:
                    return False, f"Arquivo original ainda não apareceu: {name}"
        return True, "Interface ZTE original confirmada"
    except (requests.RequestException, OSError) as exc:
        return False, type(exc).__name__


def _wait_stock(ip, stock, source_ip, log, timeout=240):
    deadline = time.monotonic() + timeout
    last = "Aguardando a ONT"
    while time.monotonic() < deadline:
        ok, last = verify_stock_web(ip, stock, source_ip)
        if ok:
            return
        time.sleep(5)
    raise TimeoutError("A interface original não apareceu após reiniciar: " + last)


def _read_block(telnet, access, profile, bank, destination, offset=None):
    remote = "/upgtempfile/f6201b_restore_read.bin"
    size = profile["block_size"]
    if offset is None:
        offset = profile["block_offset_in_partition"]
    output = telnet.run(f"mtd_debug read /dev/{bank} {offset} {size} {remote}", timeout=45)
    if f"Copied {size} bytes" not in output:
        raise RuntimeError("Não foi possível copiar o bloco de interface")
    data = receive_file(telnet, access.local_ip, telnet.router_ip, remote,
                        destination.stem + ".bin", destination, size)
    telnet.run(f"rm -f {remote}")
    return data


def _plan_bank_restore(telnet, access, profile, bank, stock, folder):
    """Inspect used UI layers and restore the latest one or use a new empty block."""
    base = profile["block_offset_in_partition"]
    block_size = profile["block_size"]
    versions: dict[int, int] = {}
    latest = None
    first_empty = None
    for slot in range(8):
        offset = base + slot * block_size
        if offset + block_size > 0x2000000:
            break
        block = _read_block(telnet, access, profile, bank,
                            folder / f"{bank}_slot_{slot}_before.bin", offset)
        if block == b"\xff" * block_size:
            first_empty = (slot, offset, block)
            break
        found, _ = parse_overlay(block, profile)
        for ino, version in found.items():
            versions[ino] = max(version, versions.get(ino, 0))
        latest = (slot, offset, block)
    if latest is None:
        if first_empty is None:
            raise RuntimeError("Não foi encontrado um bloco de interface válido")
        slot, offset, block = first_empty
        return slot, offset, block, 0, b"", block
    slot, offset, block = latest
    latest_files = overlay_files(block, profile)
    if latest_files and all(content == stock[name] for name, content in latest_files.items()):
        return slot, offset, block, 0, b"", block
    try:
        start, payload, expected = build_restore_payload(block, profile, stock)
        return slot, offset, block, start, payload, expected
    except RuntimeError as exc:
        if "não cabe no bloco disponível" not in str(exc):
            raise
    if first_empty is None:
        raise RuntimeError("Não há bloco vazio para restaurar a interface")
    slot, offset, block = first_empty
    start, payload, expected = _fresh_stock_payload(profile, stock, versions)
    return slot, offset, block, start, payload, expected


def _active(telnet, profile):
    from engine import _detect_version

    if _detect_version(telnet) != profile["version"]:
        raise RuntimeError("A versão mudou durante a restauração")
    active = active_bank(telnet.run("cat /proc/cmdline"))
    if active == "mtd7":
        return "mtd7", "mtd8", 1
    if active == "mtd8":
        return "mtd8", "mtd7", 0


def _check_device(telnet, bank):
    parts = telnet.run("cat /proc/mtd")
    if not re.search(rf'{bank}:\s+02000000\s+00020000\s+"kernel[12]"', parts):
        raise RuntimeError("Layout da flash incompatível")
    uid = telnet.run("cat /proc/self/status")
    if not re.search(r"(?m)^Uid:\s+0\s+0\s+0\s+0\s*$", uid):
        raise RuntimeError("Telnet sem permissão root")
    if "0x400" not in telnet.run(f"cat /sys/class/mtd/{bank}/flags").lower():
        raise RuntimeError("Banco inativo não permite escrita")


def _write_one(telnet, access, profile, bank, region, plan, folder, log):
    slot, offset, before, start, payload, expected = plan
    if payload:
        _check_device(telnet, bank)
        remote = "/upgtempfile/f6201b_restore_payload.bin"
        send_file(telnet, access.local_ip, telnet.router_ip,
                  "f6201b_restore_payload.bin", remote, payload)
        ram = receive_file(telnet, access.local_ip, telnet.router_ip, remote,
                           "f6201b_restore_ram.bin", folder / f"{bank}_ram.bin", len(payload))
        if ram != payload:
            raise RuntimeError("Arquivo de restauração recebido incorretamente")
        pages = len(payload) // profile["page_size"]
        seek = (offset + start) // profile["page_size"]
        log(f"Restaurando interface original no {bank}...")
        answer = telnet.run(f"dd if={remote} of=/dev/{bank} bs={profile['page_size']} "
                            f"seek={seek} count={pages} conv=notrunc", timeout=90)
        if f"{pages}+0 records in" not in answer or f"{pages}+0 records out" not in answer:
            raise RuntimeError("Gravação incompleta; banco não será trocado")
        telnet.run("sync")
        after = _read_block(telnet, access, profile, bank,
                            folder / f"{bank}_slot_{slot}_after.bin", offset)
        if after != expected:
            raise RuntimeError("Leitura pós-gravação diferente; banco não será trocado")
        telnet.run(f"rm -f {remote}")
        log(f"{bank} conferido byte por byte.")
    selected = telnet.run("upgradetest switchver", timeout=30)
    if f"switched to region {region}" not in selected or "Please reboot ONT" not in selected:
        raise RuntimeError("Troca de banco não confirmada")
    telnet.run("sync")
    telnet.reboot()


def restore_standard(router_ip: str, web_user: str, web_password: str, log) -> Path:
    from engine import _detect_version

    ip = (str(ipaddress.IPv4Address(router_ip.strip())) if router_ip.strip()
          else discover_router(log))
    if not web_user or not web_password:
        raise ValueError("Informe usuário e senha web")
    access = open_telnet(ip, web_user, web_password, log)
    folder = APP / "backups" / (datetime.now().strftime("%Y%m%d_%H%M%S") + "_restauracao_" + access.server_mac.hex())
    folder.mkdir(parents=True, exist_ok=False)
    with TelnetSession(ip, access.username, access.password, access.local_ip) as telnet:
        profile = load_profile(_detect_version(telnet))
        stock = load_stock_files(profile)
        active, inactive, region = _active(telnet, profile)
        _check_device(telnet, inactive)
        log("Salvando e conferindo as camadas de interface dos dois bancos...")
        plans = {bank: _plan_bank_restore(telnet, access, profile, bank, stock, folder)
                 for bank in (active, inactive)}
        (folder / "resultado.json").write_text(json.dumps({
            "modelo": profile["model"], "versao": profile["version"],
            "ip": ip, "banco_ativo_antes": active,
            "blocos_sha256": {bank: sha256(plans[bank][2]).hexdigest() for bank in plans},
            "blocos_destino": {bank: plans[bank][0] for bank in plans},
            "restauracao": "interface web original; configuracoes operacionais preservadas",
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if not plans[active][4] and not plans[inactive][4]:
            ok, message = verify_stock_web(ip, stock, access.local_ip)
            if not ok:
                raise RuntimeError("Blocos vazios, mas interface original não confirmada: " + message)
            log("A interface ZTE já está no padrão original.")
            return folder
        _write_one(telnet, access, profile, inactive, region,
                   plans[inactive], folder, log)
    _wait_stock(ip, stock, access.local_ip, log)
    log("Primeiro banco restaurado e confirmado na página web.")
    access = open_telnet(ip, web_user, web_password, log)
    with TelnetSession(ip, access.username, access.password, access.local_ip) as telnet:
        now_active, now_inactive, region = _active(telnet, profile)
        if now_active != inactive or now_inactive != active:
            raise RuntimeError("Banco ativo inesperado após reiniciar")
        current = _read_block(telnet, access, profile, active,
                              folder / f"{active}_before_second.bin", plans[active][1])
        if current != plans[active][2]:
            raise RuntimeError("O segundo banco mudou durante o processo")
        _write_one(telnet, access, profile, active, region,
                   plans[active], folder, log)
    _wait_stock(ip, stock, access.local_ip, log)
    log("Interface ZTE original confirmada nos dois bancos.")
    return folder
