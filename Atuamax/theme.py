"""Build the validated Atuamax theme as JFFS2 nodes for a stock F6201B bank."""

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import struct
import zlib


APP = Path(__file__).resolve().parent
TOKEN = b'&?login_001;<%=_G.encodeHTML(env.getenv("WEBTitle"))%>&?login_019;'
REQUIRED_FILE_ORDER = ("login.css", "Logo_ZTE.png", "template.css", "commonpage.css", "home.css", "login_t.lp")
FILE_ORDER = REQUIRED_FILE_ORDER + ("wlan_client_stat_js.lp",)


def jffs_crc(data: bytes) -> int:
    return zlib.crc32(data, 0xFFFFFFFF) ^ 0xFFFFFFFF


def load_profile(version: str = "V9.3.10P7N6") -> dict:
    filename = {
        "V9.3.10P7N6": "profile.json",
        "V9.3.10P7N7": "profile_n7.json",
    }.get(version)
    if filename is None:
        raise RuntimeError(f"Firmware {version} ainda não possui perfil validado")
    profile = json.loads((APP / filename).read_text(encoding="utf-8"))
    resource_dir = APP / profile.get("resource_dir", "resources")
    for name, expected in profile["resource_sha256"].items():
        actual = sha256((resource_dir / name).read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f"Recurso alterado: {name}")
    return profile


def make_inode(header: bytes, ino: int, version: int, size: int, offset: int, content: bytes) -> bytes:
    node = bytearray(header)
    if len(node) != 68 or struct.unpack_from("<HH", node) != (0x1985, 0xE002):
        raise ValueError("Cabeçalho JFFS2 inválido")
    if struct.unpack_from("<I", node, 12)[0] != ino:
        raise ValueError("Inode JFFS2 inesperado")
    struct.pack_into("<I", node, 4, 68 + len(content))
    struct.pack_into("<I", node, 8, jffs_crc(node[:8]))
    struct.pack_into("<I", node, 16, version)
    struct.pack_into("<I", node, 28, size)
    struct.pack_into("<I", node, 44, offset)
    struct.pack_into("<I", node, 48, len(content))
    struct.pack_into("<I", node, 52, len(content))
    struct.pack_into("<BBH", node, 56, 0, 0, 0)
    struct.pack_into("<I", node, 60, jffs_crc(content))
    struct.pack_into("<I", node, 64, jffs_crc(node[:60]))
    result = bytes(node) + content
    return result + b"\xff" * (-len(result) % 4)


@dataclass(frozen=True)
class BuiltTheme:
    title: str
    files: dict[str, bytes]
    payload: bytes
    block: bytes


def build_theme(profile: dict, title: str, logo_path: Path,
                version_floor: dict[int, int] | None = None) -> BuiltTheme:
    title = title.strip()
    if not title or any(ord(c) < 32 for c in title):
        raise ValueError("Informe uma mensagem de boas-vindas válida")
    title_bytes = title.encode("utf-8")
    if len(title_bytes) > len(TOKEN):
        raise ValueError(f"A mensagem pode ter até {len(TOKEN)} bytes em UTF-8")
    logo = logo_path.read_bytes()
    if len(logo) < 24 or logo[:8] != b"\x89PNG\r\n\x1a\n" or logo[12:16] != b"IHDR":
        raise ValueError("A logo precisa ser um arquivo PNG válido")
    width, height = struct.unpack_from(">II", logo, 16)
    if not (1 <= width <= 512 and 1 <= height <= 512) or len(logo) > 70000:
        raise ValueError("Logo muito grande; use até 512×512 pixels e 70 KB")
    resource_dir = APP / profile.get("resource_dir", "resources")
    files = {name: (resource_dir / name).read_bytes() for name in FILE_ORDER}
    files["Logo_ZTE.png"] = logo
    original_login = files["login_t.lp"]
    if original_login.count(TOKEN) != 1:
        raise RuntimeError("Modelo de login incompatível")
    files["login_t.lp"] = original_login.replace(TOKEN, title_bytes + b" " * (len(TOKEN) - len(title_bytes)))
    pieces = []
    version_floor = version_floor or {}
    chunk_size = profile["chunk_size"]
    for name in FILE_ORDER:
        meta = profile["inodes"][name]
        header = bytes.fromhex(meta["header_hex"])
        content = files[name]
        for index, offset in enumerate(range(0, len(content), chunk_size), 1):
            base_version = max(meta["highest_version"], version_floor.get(meta["ino"], 0))
            pieces.append(make_inode(header, meta["ino"], base_version + index, len(content), offset, content[offset:offset + chunk_size]))
    nodes = b"".join(pieces)
    page_size = profile["page_size"]
    block_size = profile["block_size"]
    payload = nodes + b"\xff" * (-len(nodes) % page_size)
    if len(payload) > block_size:
        raise ValueError("Arquivos personalizados excedem o espaço reservado da flash")
    block = payload + b"\xff" * (block_size - len(payload))
    return BuiltTheme(title, files, payload, block)
