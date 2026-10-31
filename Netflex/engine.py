"""Verified F6201B customization workflow, one device per run."""

from datetime import datetime
from hashlib import sha256
import ipaddress
import json
from pathlib import Path
import re
import struct
import time
import zlib

import requests

from brand import load_brand
from boot import active_bank
from factory_auth import BoundAdapter, discover_router, local_route_and_mac, open_telnet
from recovery import parse_overlay
from theme import APP, BuiltTheme, build_theme, load_profile
from transport import TelnetSession, receive_file, send_file
from wifi import apply_names, name_from_mac, verify_names


def _file_hash(data: bytes) -> str:
    return sha256(data).hexdigest()


def _valid_wrapped_n6(bank: bytes, profile: dict) -> bool:
    """Accept the N6 firmware wrapper only around the verified stock rootfs."""
    rootfs_offset = 0x20000
    data_offset = 0x168
    return (
        bank[:16] == bytes.fromhex("999999994444444455555555aaaaaaaa")
        and profile["model"].encode() in bank[:512]
        and profile["version"].encode() in bank[:512]
        and struct.unpack_from("<I", bank, 0x6C)[0] == len(bank)
        and struct.unpack_from("<I", bank, 0x70)[0] == len(bank) - data_offset
        and struct.unpack_from("<I", bank, 0x74)[0] == data_offset
        and struct.unpack_from("<I", bank, 0x80)[0] == len(bank)
        and zlib.crc32(bank[data_offset:]) == struct.unpack_from("<I", bank, 0x78)[0]
        and bank[rootfs_offset:rootfs_offset + 4] == bytes.fromhex("851901e0")
        and _file_hash(bank[rootfs_offset:]) == profile["wrapped_rootfs_sha256"]
        and profile.get("bank_image_offset", 131072) + len(bank)
            == profile["block_offset_in_partition"]
    )


def _validate_bank_image(bank: bytes, profile: dict, bank_name: str) -> str:
    expected_size = profile["bank_image_size"]
    if len(bank) != expected_size:
        raise RuntimeError("Backup do banco com tamanho inesperado")
    bank_hash = _file_hash(bank)
    if profile["version"] == "V9.3.10P7N6":
        if bank_hash == profile["bank_sha256"][bank_name]:
            # Older N6 banks store the rootfs directly after partition offset 0x20000.
            if bank[:4] != bytes.fromhex("851901e0"):
                raise RuntimeError("Cabeçalho JFFS2 do firmware N6 inválido")
        elif not _valid_wrapped_n6(bank, profile):
            raise RuntimeError("Imagem N6 diferente das variantes validadas. Nenhuma gravação feita.")
    else:
        if bank_hash != profile["bank_sha256"][bank_name]:
            raise RuntimeError("O banco inativo difere da imagem original validada. Nenhuma gravação feita.")
        if bank[:16] != bytes.fromhex("999999994444444455555555aaaaaaaa"):
            raise RuntimeError("Cabeçalho de firmware desconhecido")
        if profile["model"].encode() not in bank[:512] or profile["version"].encode() not in bank[:512]:
            raise RuntimeError("Modelo ou versão incompatível no banco inativo")
        if zlib.crc32(bank[0x168:]) != struct.unpack_from("<I", bank, 0x78)[0]:
            raise RuntimeError("CRC da imagem original inválido")
    return bank_hash


def _http_get(router_ip: str, path: str, source_ip: str | None = None) -> bytes:
    with requests.Session() as session:
        session.trust_env = False
        if source_ip:
            session.mount("http://", BoundAdapter(source_ip))
        response = session.get(f"http://{router_ip}{path}", params={"t": time.time_ns()}, timeout=4)
        response.raise_for_status()
        return response.content


def verify_web(router_ip: str, theme: BuiltTheme, source_ip: str | None = None) -> tuple[bool, str]:
    try:
        page = _http_get(router_ip, "/", source_ip)
        if theme.title.encode("utf-8") not in page:
            return False, "A frase de boas-vindas ainda não corresponde"
        paths = {
            "login.css": "/css/login.css",
            "template.css": "/css/template.css",
            "commonpage.css": "/css/commonpage.css",
            "home.css": "/css/home.css",
            "Logo_ZTE.png": "/img/Logo_ZTE.png",
        }
        for name, path in paths.items():
            if _http_get(router_ip, path, source_ip) != theme.files[name]:
                return False, f"Arquivo servido diferente: {name}"
        return True, "Frase, logo e estilos conferidos"
    except (requests.RequestException, OSError) as exc:
        return False, type(exc).__name__


def _wait_for_theme(router_ip: str, theme: BuiltTheme, log, timeout: int = 240,
                    source_ip: str | None = None):
    deadline = time.monotonic() + timeout
    last_message = 0.0
    last_error = "Sem resposta da interface"
    while time.monotonic() < deadline:
        ok, message = verify_web(router_ip, theme, source_ip)
        if ok:
            return
        last_error = message
        if time.monotonic() - last_message >= 20:
            log("Aguardando a página após reiniciar: " + message)
            last_message = time.monotonic()
        time.sleep(5)
    raise TimeoutError("A personalização não apareceu após reiniciar: " + last_error)


def _unique_backup_dir(mac: bytes) -> Path:
    root = APP / "backups"
    root.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder = root / f"{stamp}_{mac.hex()}"
    folder.mkdir(exist_ok=False)
    return folder


def _run_checked(telnet: TelnetSession, command: str, expected: str, timeout: int = 45):
    result = telnet.run(command, timeout)
    if expected not in result:
        raise RuntimeError(f"Resposta inesperada ao ler a flash: {command}")
    return result


def _detect_version(telnet: TelnetSession) -> str:
    result = telnet.run("upgradetest getver")
    versions = re.findall(r"region:[01],\s*version num:(V[0-9A-Za-z.]+)", result)
    if len(versions) != 2 or versions[0] != versions[1]:
        raise RuntimeError("Não foi possível identificar uma versão igual nos dois bancos")
    return versions[0]


def _inspect(telnet: TelnetSession, profile: dict, log) -> tuple[str, int]:
    version = profile["version"]
    active = active_bank(telnet.run("cat /proc/cmdline"))
    if active == "mtd7":
        inactive, region = "mtd8", 1
    elif active == "mtd8":
        inactive, region = "mtd7", 0
    partitions = telnet.run("cat /proc/mtd")
    if not re.search(r'mtd7:\s+02000000\s+00020000\s+"kernel1"', partitions):
        raise RuntimeError("Partição kernel1 diferente do perfil validado")
    if not re.search(r'mtd8:\s+02000000\s+00020000\s+"kernel2"', partitions):
        raise RuntimeError("Partição kernel2 diferente do perfil validado")
    identity = telnet.run("cat /proc/self/status")
    if not re.search(r"(?m)^Uid:\s+0\s+0\s+0\s+0\s*$", identity):
        raise RuntimeError("A sessão Telnet não tem permissão root")
    flags = telnet.run(f"cat /sys/class/mtd/{inactive}/flags")
    if "0x400" not in flags.lower():
        raise RuntimeError("O banco inativo não permite escrita")
    log(f"F6201B {version}: banco {region} inativo identificado.")
    return inactive, region


def _select_theme_slot(telnet: TelnetSession, access, profile: dict, bank: str,
                       backup_dir: Path, log) -> tuple[int, int, dict[int, int], bytes]:
    """Use the first erased JFFS2 block after existing validated UI layers."""
    block_size = profile["block_size"]
    base = profile["block_offset_in_partition"]
    versions: dict[int, int] = {}
    remote = "/upgtempfile/f6201b_auto_block.bin"
    for slot in range(8):
        offset = base + slot * block_size
        if offset + block_size > 0x2000000:
            break
        _run_checked(telnet, f"mtd_debug read /dev/{bank} {offset} {block_size} {remote}",
                     f"Copied {block_size} bytes")
        block = receive_file(telnet, access.local_ip, telnet.router_ip, remote,
                             f"f6201b_auto_slot_{slot}.bin",
                             backup_dir / f"block_slot_{slot}_before.bin", block_size)
        telnet.run(f"rm -f {remote}")
        if block == b"\xff" * block_size:
            if slot:
                log(f"{slot} camada(s) de interface anterior(es) encontrada(s); usando bloco livre seguinte.")
            return slot, offset, versions, block
        found, _ = parse_overlay(block, profile)
        for ino, version in found.items():
            versions[ino] = max(version, versions.get(ino, 0))
    raise RuntimeError("Não há bloco validado e vazio para nova personalização")


def customize(router_ip: str, web_user: str, web_password: str, title: str,
              logo_path: Path, set_wifi: bool, log, _second_pass: bool = False) -> Path:
    router_ip = (str(ipaddress.IPv4Address(router_ip.strip())) if router_ip.strip()
                 else discover_router(log))
    if not web_user or not web_password:
        raise ValueError("Informe usuário e senha web")
    factory = open_telnet(router_ip, web_user, web_password, log)
    backup_dir = _unique_backup_dir(factory.server_mac)
    log("Cópias de segurança: " + str(backup_dir))
    inactive = ""
    region = -1
    remote_backup = "/upgtempfile/f6201b_auto_bank.bin"
    remote_block = "/upgtempfile/f6201b_auto_block.bin"
    remote_payload = "/upgtempfile/f6201b_auto_theme.bin"
    remote_readback = "/upgtempfile/f6201b_auto_readback.bin"
    try:
        with TelnetSession(router_ip, factory.username, factory.password, factory.local_ip) as telnet:
            version = _detect_version(telnet)
            profile = load_profile(version)
            log(f"Firmware {version} detectado; conferindo espaço para a personalização.")
            inactive, region = _inspect(telnet, profile, log)
            image_size = profile["bank_image_size"]
            image_offset = profile.get("bank_image_offset", 131072)
            log("Lendo o banco inativo para backup e identificação...")
            _run_checked(
                telnet,
                f"mtd_debug read /dev/{inactive} {image_offset} {image_size} {remote_backup}",
                f"Copied {image_size} bytes", timeout=180,
            )
            bank_file = backup_dir / f"{inactive}_original.bin"
            bank = receive_file(
                telnet, factory.local_ip, router_ip, remote_backup, "f6201b_auto_bank.bin",
                bank_file, image_size,
                progress=lambda done, total: log(f"Backup: {done // 1048576}/{total // 1048576} MiB"),
            )
            telnet.run(f"rm -f {remote_backup}")
            bank_hash = _validate_bank_image(bank, profile, inactive)
            if version == "V9.3.10P7N6" and bank_hash != profile["bank_sha256"][inactive]:
                log("Variante N6 com cabeçalho de firmware validada.")
            (backup_dir / "backup.sha256").write_text(f"{bank_hash}  {bank_file.name}\n", encoding="ascii")
            log("Backup salvo e conferido.")
            slot, offset, versions, before = _select_theme_slot(
                telnet, factory, profile, inactive, backup_dir, log)
            block_size = profile["block_size"]
            theme = build_theme(profile, title, logo_path, versions)
            log(f"Tema preparado para o bloco {slot + 1}; arquivos e espaço conferidos.")
            wifi_name = None
            if set_wifi:
                wifi_name = apply_names(telnet, factory.server_mac, factory.local_ip,
                                        router_ip, backup_dir, log, load_brand()["wifi_prefix"])
            log("Bloco de destino vazio; enviando a personalização...")
            send_file(telnet, factory.local_ip, router_ip, "f6201b_auto_theme.bin", remote_payload, theme.payload)
            ram = receive_file(telnet, factory.local_ip, router_ip, remote_payload,
                               "f6201b_auto_ram.bin", backup_dir / "payload_ram.bin", len(theme.payload))
            if ram != theme.payload:
                raise RuntimeError("Arquivo recebido na RAM difere; nenhuma gravação feita")
            pages = len(theme.payload) // profile["page_size"]
            seek = offset // profile["page_size"]
            log(f"Gravando {pages} páginas no banco inativo...")
            written = telnet.run(
                f"dd if={remote_payload} of=/dev/{inactive} bs={profile['page_size']} seek={seek} count={pages} conv=notrunc",
                timeout=90,
            )
            if f"{pages}+0 records in" not in written or f"{pages}+0 records out" not in written:
                raise RuntimeError("Gravação incompleta; não trocar o banco de boot")
            telnet.run("sync")
            _run_checked(telnet, f"mtd_debug read /dev/{inactive} {offset} {block_size} {remote_readback}",
                         f"Copied {block_size} bytes")
            after = receive_file(telnet, factory.local_ip, router_ip, remote_readback,
                                 "f6201b_auto_readback.bin", backup_dir / "block_after.bin", block_size)
            if after != theme.block:
                raise RuntimeError("Leitura pós-gravação diferente; não trocar o banco de boot")
            log("Bloco gravado e verificado byte por byte.")
            manifest = {
                "modelo": profile["model"], "versao": profile["version"],
                "ip": router_ip, "mac": factory.server_mac.hex(":"),
                "banco_gravado": inactive, "bloco": slot, "bloco_offset": offset,
                "backup_sha256": bank_hash,
                "bloco_sha256": _file_hash(after), "mensagem": theme.title,
                "wifi_nome": wifi_name,
                "arquivos_sha256": {name: _file_hash(data) for name, data in theme.files.items()},
            }
            (backup_dir / "resultado.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            telnet.run(f"rm -f {remote_backup} {remote_block} {remote_payload} {remote_readback}")
            selected = telnet.run("upgradetest switchver", timeout=30)
            if f"switched to region {region}" not in selected or "Please reboot ONT" not in selected:
                raise RuntimeError("Troca de banco não confirmada; verifique o estado antes de reiniciar")
            telnet.run("sync")
            log("Iniciando a ONT pelo banco personalizado...")
            telnet.reboot()
    finally:
        factory.password = ""
    _wait_for_theme(router_ip, theme, log, source_ip=factory.local_ip)
    if not _second_pass:
        log("Primeiro banco confirmado. Personalizando o segundo banco...")
        second_backup = customize(router_ip, web_user, web_password, title, logo_path,
                                  False, log, _second_pass=True)
        result_path = backup_dir / "resultado.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["segundo_banco_backup"] = str(second_backup)
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        log("Os dois bancos foram personalizados e conferidos.")
    if set_wifi:
        log("Conferindo os nomes das duas redes Wi-Fi após reiniciar...")
        access = open_telnet(router_ip, web_user, web_password, log)
        with TelnetSession(router_ip, access.username, access.password, access.local_ip) as telnet:
            verify_names(telnet, name_from_mac(access.server_mac, load_brand()["wifi_prefix"]))
        log("Nomes das redes 2,4 e 5 GHz confirmados.")
    log("Personalização concluída. Frase, logo e menus verificados após reiniciar.")
    return backup_dir


def watch_physical_reset(router_ip: str, title: str, logo_path: Path, web_user: str,
                         web_password: str, check_wifi: bool, log, timeout: int = 600):
    router_ip = (str(ipaddress.IPv4Address(router_ip.strip())) if router_ip.strip()
                 else discover_router(log))
    access = open_telnet(router_ip, web_user, web_password, log)
    with TelnetSession(router_ip, access.username, access.password, access.local_ip) as telnet:
        profile = load_profile(_detect_version(telnet))
    theme = build_theme(profile, title, logo_path)
    source_ip, _ = local_route_and_mac(router_ip)
    deadline = time.monotonic() + timeout
    failures = 0
    went_down = False
    last_log = 0.0
    while time.monotonic() < deadline:
        now = time.monotonic()
        try:
            _http_get(router_ip, "/", source_ip)
            failures = 0
            if went_down:
                _wait_for_theme(router_ip, theme, log, timeout=240, source_ip=source_ip)
                if check_wifi:
                    access = open_telnet(router_ip, web_user, web_password, log)
                    with TelnetSession(router_ip, access.username, access.password, access.local_ip) as telnet:
                        verify_names(telnet, name_from_mac(access.server_mac, load_brand()["wifi_prefix"]))
                    log("Redes Wi-Fi também preservadas após o reset físico.")
                log("Reset físico confirmado: personalização preservada.")
                return
            if now - last_log >= 30:
                log("Aguardando você pressionar o reset físico...")
                last_log = now
        except (requests.RequestException, OSError):
            failures += 1
            if failures >= 3 and not went_down:
                went_down = True
                log("A ONT saiu da rede; aguardando a inicialização...")
            elif went_down and now - last_log >= 30:
                log("Aguardando a ONT voltar...")
                last_log = now
        time.sleep(3)
    raise TimeoutError("O ciclo de reset físico não foi observado em dez minutos")
