"""Open temporary F6201B Telnet using the tested re_rand factory protocol."""

from dataclasses import dataclass, field
import ipaddress
import json
import re
import socket
import subprocess
import time
from urllib.parse import parse_qs, urlparse

from Crypto.Cipher import AES
import requests
from requests.adapters import HTTPAdapter

KEY_POOL = [
    0x9c, 0x33, 0x75, 0xd1, 0x1c, 0x42, 0x45, 0x37, 0x18, 0x48,
    0x91, 0x73, 0x17, 0x45, 0x79, 0x44, 0x43, 0xd7, 0xd5, 0x73,
    0x33, 0x54, 0x76, 0xd2, 0xc5, 0xf1, 0x2c, 0x4f, 0x7a, 0xba,
    0x61, 0xd9, 0x5c, 0x69, 0xdf, 0x8c, 0xd2, 0x1c, 0xde, 0x3b,
    0x35, 0x2d, 0x2f, 0xe1, 0xde, 0x4c, 0x77, 0xf5, 0x1a, 0x65,
    0xd1, 0xfe, 0x18, 0x43, 0x8e, 0xa7, 0x42, 0x08, 0x04, 0x78,
    0xd5, 0xe4, 0xf3, 0x34, 0xa4, 0xd3, 0xf2, 0x36, 0x47, 0x6d,
    0x86, 0x9d, 0x42, 0x65, 0x13, 0x42, 0xdc, 0x42, 0x99, 0x48,
    0xdc, 0x67, 0x9f, 0x9e, 0xdc, 0x46, 0x37, 0x5f, 0x84, 0x9f,
    0x6f, 0x76, 0xce, 0x79, 0x4f, 0x49,
]
TIMEOUT = 8


class BoundAdapter(HTTPAdapter):
    def __init__(self, local_ip: str):
        self.local_ip = local_ip
        super().__init__()

    def init_poolmanager(self, connections, maxsize, block=False, **kwargs):
        kwargs["source_address"] = (self.local_ip, 0)
        return super().init_poolmanager(connections, maxsize, block=block, **kwargs)


@dataclass(repr=False)
class FactoryAccess:
    username: str
    password: str = field(repr=False)
    server_mac: bytes = field(repr=False)
    local_mac: bytes = field(repr=False)
    local_ip: str = ""


def local_route_and_mac(router_ip: str) -> tuple[str, bytes]:
    script = (
        "Get-NetIPAddress -AddressFamily IPv4 | ForEach-Object { "
        "$a = Get-NetAdapter -InterfaceIndex $_.InterfaceIndex -ErrorAction SilentlyContinue; "
        "if ($a) { [pscustomobject]@{ip=$_.IPAddress; prefix=$_.PrefixLength; "
        "mac=$a.MacAddress; status=[string]$a.Status} } } | ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=45,
    )
    if result.returncode:
        raise RuntimeError(f"Não foi possível identificar a placa Ethernet usada para {router_ip}")
    try:
        addresses = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("A lista de placas de rede não pôde ser lida") from exc
    if isinstance(addresses, dict):
        addresses = [addresses]
    router = ipaddress.IPv4Address(router_ip)
    matches = []
    for entry in addresses:
        try:
            local = ipaddress.IPv4Address(entry["ip"])
            network = ipaddress.IPv4Network(f"{local}/{entry['prefix']}", strict=False)
            if router in network and local != router and entry["status"] == "Up":
                matches.append((int(entry["prefix"]), str(local), entry["mac"]))
        except (KeyError, ValueError):
            continue
    if not matches:
        raise RuntimeError(f"Não há placa Ethernet ativa na mesma rede de {router_ip}")
    _, local_ip, mac_text = max(matches)
    try:
        mac = bytes.fromhex(re.sub(r"[^0-9a-fA-F]", "", mac_text))
    except ValueError as exc:
        raise RuntimeError("MAC local inválido") from exc
    if len(mac) != 6:
        raise RuntimeError("A placa de rede não informou um MAC de 6 bytes")
    try:
        with socket.create_connection((router_ip, 80), timeout=5, source_address=(local_ip, 0)):
            pass
    except OSError as exc:
        raise RuntimeError(f"A Ethernet {local_ip} não alcança {router_ip}: {exc}") from exc
    return local_ip, mac


def discover_router(log=None) -> str:
    """Find a connected F6201B through active Windows IPv4 interfaces."""
    script = (
        "Get-NetIPAddress -AddressFamily IPv4 | ForEach-Object { "
        "$a = Get-NetAdapter -InterfaceIndex $_.InterfaceIndex -ErrorAction SilentlyContinue; "
        "if ($a -and $a.Status -eq 'Up') { [pscustomobject]@{alias=$a.Name; "
        "ip=$_.IPAddress; prefix=$_.PrefixLength} } } | ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=20,
    )
    if result.returncode:
        raise RuntimeError("Não foi possível examinar as conexões de rede do Windows")
    try:
        interfaces = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("O Windows não informou as conexões de rede") from exc
    if isinstance(interfaces, dict):
        interfaces = [interfaces]
    candidates = []
    for item in interfaces:
        try:
            source = ipaddress.IPv4Address(item["ip"])
            network = ipaddress.IPv4Network(f"{source}/{item['prefix']}", strict=False)
            alias = (item.get("alias") or "").lower()
            priority = 0 if "ethernet" in alias and "vethernet" not in alias else 1
            possibilities = []
            if network.prefixlen <= 30:
                possibilities.append(str(next(network.hosts())))
                possibilities.append(str(network.broadcast_address - 1))
            possibilities.extend(("192.168.1.1", "192.168.0.1", "192.168.100.1"))
            for ip in possibilities:
                if ip and ipaddress.IPv4Address(ip) in network and ip != str(source):
                    candidates.append((priority, ip, str(source)))
        except (KeyError, ValueError, StopIteration):
            continue
    seen = set()
    for _, router, source in sorted(candidates):
        if (router, source) in seen:
            continue
        seen.add((router, source))
        try:
            with requests.Session() as session:
                session.trust_env = False
                session.mount("http://", BoundAdapter(source))
                response = session.get(f"http://{router}/", timeout=3)
                page = response.content
            if response.status_code == 200 and (
                b"&#70;&#54;&#50;&#48;&#49;&#66;" in page or
                (b"login.css" in page and b"Frm_Username" in page)
            ):
                if log:
                    log(f"F6201B encontrada em {router} pela conexão {source}.")
                return router
        except (OSError, requests.RequestException):
            continue
    raise RuntimeError("Nenhuma F6201B encontrada. Conecte a ONT à Ethernet e aguarde a rede ficar pronta")


def pad(data: bytes) -> bytes:
    return data + b"\x00" * (-len(data) % 16 or 16)


def _open_telnet_once(router_ip: str, web_user: str, web_password: str, log) -> FactoryAccess:
    from rss import create_payload_array, verify_do_check_client

    local_ip, local_mac = local_route_and_mac(router_ip)
    log(f"Rede local identificada: {local_ip}")
    root = f"http://{router_ip}"
    session = requests.Session()
    session.trust_env = False
    session.mount("http://", BoundAdapter(local_ip))
    log("Solicitando acesso temporário ao equipamento...")
    reset = session.post(root + "/webFac", data="SendSq.gch", timeout=TIMEOUT)
    if reset.status_code != 400:
        raise RuntimeError(f"Etapa inicial recusada (HTTP {reset.status_code})")
    try:
        session.post(root + "/webFac", data="RequestFactoryMode.gch", timeout=TIMEOUT)
    except (requests.ConnectionError, requests.Timeout):
        pass
    challenge = None
    for attempt in range(3):
        try:
            challenge = session.post(root + "/webFac", data="SendSq.gch?rand=0\r\n", timeout=TIMEOUT)
            if challenge.status_code == 200:
                break
        except (requests.ConnectionError, requests.Timeout):
            pass
        time.sleep(2)
    if challenge is None or challenge.status_code != 200:
        raise RuntimeError("A ONT não respondeu ao desafio re_rand")
    match = re.fullmatch(rb"re_rand=(\d+)&(\d+)&(.{6})", challenge.content, re.DOTALL)
    if match is None:
        raise RuntimeError("Resposta re_rand incompatível com o firmware validado")
    server_rand = int(match.group(1))
    server_mac = match.group(3)
    if not 0 <= server_rand <= 59:
        raise RuntimeError("Índice do desafio re_rand fora do intervalo esperado")
    key = bytes((value ^ 0xA5) & 0xFF for value in KEY_POOL[server_rand:server_rand + 24])
    if len(key) != 24:
        raise RuntimeError("Chave do protocolo incompleta")
    aes = AES.new(key, AES.MODE_ECB)
    payload_array = create_payload_array(server_mac, local_mac, server_rand)
    if not verify_do_check_client(payload_array, local_mac, server_rand, server_mac):
        raise RuntimeError("A verificação do MAC local falhou")
    values = b"".join(value.to_bytes(4, "little") for value in payload_array).decode("ascii")
    send_info = f"SendInfo.gch?info={len(payload_array)}|{values}".encode("ascii")
    response = session.post(root + "/webFacEntry", data=aes.encrypt(pad(send_info)), timeout=TIMEOUT)
    if response.status_code != 200:
        raise RuntimeError(f"Identificação da placa de rede recusada (HTTP {response.status_code})")
    login_request = f"CheckLoginAuth.gch?version50&user={web_user}&pass={web_password}".encode("utf-8")
    response = session.post(root + "/webFacEntry", data=aes.encrypt(pad(login_request)), timeout=TIMEOUT)
    if response.status_code == 401:
        raise PermissionError("Usuário ou senha web recusados no modo de fábrica")
    if response.status_code != 200 or len(response.content) % 16:
        raise RuntimeError(f"Autenticação web falhou (HTTP {response.status_code}, {len(response.content)} bytes)")
    result = aes.decrypt(response.content).rstrip(b"\x00")
    if result != b"FactoryMode.gch":
        raise RuntimeError("A conta web não recebeu acesso ao modo de fábrica")
    mode_request = b"FactoryMode.gch?mode=2&user=notused"
    response = session.post(root + "/webFacEntry", data=aes.encrypt(pad(mode_request)), timeout=TIMEOUT)
    if response.status_code != 200 or len(response.content) % 16:
        raise RuntimeError("A ONT não gerou o acesso Telnet temporário")
    decoded = aes.decrypt(response.content).rstrip(b"\x00").decode("ascii", "strict")
    parsed = urlparse(decoded)
    values = parse_qs(parsed.query)
    if parsed.path != "FactoryModeAuth.gch" or not values.get("user") or not values.get("pass"):
        raise RuntimeError("Resposta de credenciais Telnet incompatível")
    log("Acesso Telnet temporário gerado automaticamente.")
    return FactoryAccess(values["user"][0], values["pass"][0], server_mac, local_mac, local_ip)


def open_telnet(router_ip: str, web_user: str, web_password: str, log) -> FactoryAccess:
    for attempt in range(2):
        try:
            return _open_telnet_once(router_ip, web_user, web_password, log)
        except RuntimeError as exc:
            if attempt or not str(exc).startswith("Autenticação web falhou (HTTP 200,"):
                raise
            log("A resposta de autenticação veio incompleta; repetindo o desafio...")
            time.sleep(2)
    raise RuntimeError("Não foi possível concluir a autenticação")
