"""Temporary Telnet and local TFTP transport for the F6201B."""

from pathlib import Path
import re
import socket
import struct
import telnetlib
import threading
import time


TFTP_PORT = 6969


class TelnetSession:
    def __init__(self, router_ip: str, username: str, password: str, local_ip: str | None = None):
        self.router_ip = router_ip
        self.username = username
        self.password = password
        self.local_ip = local_ip
        self.session: telnetlib.Telnet | None = None

    def __enter__(self):
        last_error = None
        for _ in range(5):
            session = None
            try:
                session = telnetlib.Telnet()
                session.sock = socket.create_connection(
                    (self.router_ip, 23), timeout=7,
                    source_address=(self.local_ip, 0) if self.local_ip else None,
                )
                if b"Login:" not in session.read_until(b"Login:", timeout=7):
                    raise RuntimeError("Prompt Telnet ausente")
                session.write(self.username.encode("ascii") + b"\r\n")
                if b"Password:" not in session.read_until(b"Password:", timeout=7):
                    raise RuntimeError("Prompt de senha Telnet ausente")
                session.write(self.password.encode("ascii") + b"\r\n")
                if b"/ #" not in session.read_until(b"/ #", timeout=9):
                    raise RuntimeError("Credenciais Telnet temporárias recusadas")
                self.session = session
                return self
            except (OSError, EOFError, RuntimeError) as exc:
                last_error = exc
                try:
                    session.close()
                except Exception:
                    pass
                time.sleep(2)
        raise RuntimeError(f"Telnet não abriu: {last_error}")

    def __exit__(self, *args):
        if self.session is not None:
            self.session.close()

    def run(self, line: str, timeout: int = 30) -> str:
        if self.session is None:
            raise RuntimeError("Telnet não conectado")
        self.session.write((line + "; echo __F6201B_EXIT__:$?\r\n").encode("ascii"))
        result = self.session.read_until(b"/ #", timeout=timeout)
        if b"/ #" not in result:
            raise RuntimeError("Resposta Telnet incompleta")
        decoded = result.decode("utf-8", "replace")
        matches = re.findall(r"__F6201B_EXIT__:(\d+)", decoded)
        if len(matches) != 1 or matches[0] != "0":
            raise RuntimeError(f"Comando da ONT falhou: {line}\n{decoded[-600:]}")
        return decoded

    def reboot(self):
        if self.session is None:
            raise RuntimeError("Telnet não conectado")
        self.session.write(b"reboot\r\n")
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            try:
                self.session.read_very_eager()
            except EOFError:
                return
            time.sleep(1)
        raise TimeoutError("A ONT não encerrou o Telnet após reboot")


class Receiver(threading.Thread):
    def __init__(self, bind_ip: str, peer_ip: str, name: str, destination: Path, size: int, progress=None):
        super().__init__(daemon=True)
        self.peer_ip = peer_ip
        self.name = name
        self.destination = destination
        self.size = size
        self.progress = progress
        self.done = threading.Event()
        self.error: Exception | None = None
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((bind_ip, TFTP_PORT))
        self.sock.settimeout(12)

    def run(self):
        partial = self.destination.with_suffix(self.destination.suffix + ".part")
        try:
            if self.destination.exists() or partial.exists():
                raise FileExistsError(f"Arquivo de backup já existe: {self.destination}")
            request, peer = self.sock.recvfrom(2048)
            fields = request[2:].split(b"\0")
            if request[:2] != b"\0\2" or fields[0].decode("ascii") != self.name:
                raise RuntimeError("Pedido TFTP inesperado")
            if peer[0] != self.peer_ip or fields[1].lower() != b"octet":
                raise RuntimeError("Origem TFTP inesperada")
            count = 0
            next_progress = 1024 * 1024
            self.sock.sendto(struct.pack("!HH", 4, 0), peer)
            with partial.open("wb") as target:
                while True:
                    packet, sender = self.sock.recvfrom(1024)
                    if sender != peer:
                        continue
                    if packet[:2] == b"\0\5":
                        raise RuntimeError("ONT recusou a transferência TFTP")
                    if len(packet) < 4 or packet[:2] != b"\0\3":
                        continue
                    block = struct.unpack("!H", packet[2:4])[0]
                    expected = ((count // 512) + 1) & 0xFFFF
                    if block == (expected - 1) & 0xFFFF:
                        self.sock.sendto(struct.pack("!HH", 4, block), peer)
                        continue
                    if block != expected:
                        raise RuntimeError(f"Bloco TFTP inesperado: {block}")
                    chunk = packet[4:]
                    count += len(chunk)
                    if count > self.size:
                        raise RuntimeError("Recebimento excedeu o tamanho esperado")
                    target.write(chunk)
                    self.sock.sendto(struct.pack("!HH", 4, block), peer)
                    if self.progress and count >= next_progress:
                        self.progress(count, self.size)
                        next_progress += 1024 * 1024
                    if len(chunk) < 512:
                        break
            if count != self.size:
                raise RuntimeError(f"Transferência incompleta: {count} de {self.size} bytes")
            partial.replace(self.destination)
        except Exception as exc:
            self.error = exc
            try:
                partial.unlink(missing_ok=True)
            except OSError:
                pass
        finally:
            self.done.set()
            self.sock.close()


class Sender(threading.Thread):
    def __init__(self, bind_ip: str, peer_ip: str, name: str, data: bytes):
        super().__init__(daemon=True)
        self.peer_ip = peer_ip
        self.name = name
        self.data = data
        self.done = threading.Event()
        self.error: Exception | None = None
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((bind_ip, TFTP_PORT))
        self.sock.settimeout(10)

    def run(self):
        try:
            request, peer = self.sock.recvfrom(2048)
            fields = request[2:].split(b"\0")
            if request[:2] != b"\0\1" or fields[0].decode("ascii") != self.name:
                raise RuntimeError("Pedido TFTP inesperado")
            if peer[0] != self.peer_ip or fields[1].lower() != b"octet":
                raise RuntimeError("Origem TFTP inesperada")
            chunks = [self.data[i:i + 512] for i in range(0, len(self.data), 512)]
            if len(self.data) % 512 == 0:
                chunks.append(b"")
            for index, chunk in enumerate(chunks, 1):
                packet = struct.pack("!HH", 3, index & 0xFFFF) + chunk
                for attempt in range(4):
                    self.sock.sendto(packet, peer)
                    try:
                        answer, sender = self.sock.recvfrom(1024)
                    except socket.timeout:
                        if attempt == 3:
                            raise
                        continue
                    if sender == peer and answer[:4] == struct.pack("!HH", 4, index & 0xFFFF):
                        break
                    if answer[:2] == b"\0\5":
                        raise RuntimeError("ONT recusou o arquivo TFTP")
                else:
                    raise RuntimeError("Confirmação TFTP ausente")
        except Exception as exc:
            self.error = exc
        finally:
            self.done.set()
            self.sock.close()


def receive_file(telnet: TelnetSession, local_ip: str, router_ip: str, remote_file: str,
                 request_name: str, destination: Path, size: int, progress=None) -> bytes:
    receiver = Receiver(local_ip, router_ip, request_name, destination, size, progress)
    receiver.start()
    try:
        telnet.run(f"tftp -l {remote_file} -r {request_name} -p {local_ip} {TFTP_PORT}", max(90, size // 100000 + 60))
        if not receiver.done.wait(15) or receiver.error:
            raise RuntimeError(f"Recebimento TFTP falhou: {receiver.error}")
    finally:
        if not receiver.done.is_set():
            receiver.sock.close()
    return destination.read_bytes()


def send_file(telnet: TelnetSession, local_ip: str, router_ip: str, name: str,
              remote_file: str, data: bytes):
    sender = Sender(local_ip, router_ip, name, data)
    sender.start()
    try:
        telnet.run(f"tftp -r {name} -l {remote_file} -g {local_ip} {TFTP_PORT}", max(60, len(data) // 100000 + 30))
        if not sender.done.wait(15) or sender.error:
            raise RuntimeError(f"Envio TFTP falhou: {sender.error}")
    finally:
        if not sender.done.is_set():
            sender.sock.close()
