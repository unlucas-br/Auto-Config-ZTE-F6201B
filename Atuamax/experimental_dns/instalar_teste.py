"""Install or refresh the Atuamax DNS test panel on a connected F6201B.

This only writes files to /Plugin (mtd10). DNS hosts/logs are kept in RAM.
The five-minute redirect is enabled separately from the web panel.
"""

from getpass import getpass
from pathlib import Path
import re
import secrets
import sys
import time
import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from factory_auth import open_telnet
from transport import TelnetSession, send_file

IP = "192.168.1.1"
BASE = "/Plugin/atuamax-dns"
TOKEN_FILE = HERE / ".local-admin-token"


def temporary_access(user, password):
    for attempt in range(3):
        try:
            return open_telnet(IP, user, password, print)
        except RuntimeError as error:
            transient = ("Identificação da placa de rede recusada (HTTP 401)" in str(error)
                         or "Autenticação web falhou (HTTP 200," in str(error))
            if attempt == 2 or not transient:
                raise
            print("Resposta de autenticação incompleta; tentando novamente...", flush=True)
            time.sleep(15)
    raise RuntimeError("Não foi possível obter acesso temporário")


def stop_exact_process(telnet, executable):
    output = telnet.run("ps")
    for line in output.splitlines():
        if executable not in line or "grep" in line:
            continue
        match = re.match(r"\s*(\d+)\s+root\b", line)
        if match:
            telnet.run(f"kill {int(match.group(1))}")
            time.sleep(1)


def main():
    files = {
        "dnsmasq": HERE / "dnsmasq-arm-softfloat",
        "dnsweb": HERE / "dnsweb-arm",
        "index.html": HERE / "index.html",
        "logo.png": HERE / "logo.png",
    }
    for file in files.values():
        if not file.is_file():
            raise SystemExit(f"Arquivo ausente: {file}")
    token = TOKEN_FILE.read_text(encoding="ascii").strip() if TOKEN_FILE.exists() else secrets.token_hex(16)
    TOKEN_FILE.write_text(token + "\n", encoding="ascii")
    user = input("Usuário web administrativo da ONT: ").strip()
    password = getpass("Senha web atual: ")
    access = temporary_access(user, password)
    with TelnetSession(IP, access.username, access.password, access.local_ip) as telnet:
        mounts = telnet.run("df -k /Plugin /Pluginlog /var")
        if "/Plugin" not in mounts or "/var" not in mounts:
            raise RuntimeError("Partições necessárias não identificadas")
        telnet.run(f"mkdir -p {BASE} /Pluginlog/atuamax-dns /var/tmp")
        stop_exact_process(telnet, f"{BASE}/dnsweb")
        stop_exact_process(telnet, f"{BASE}/dnsmasq")
        stop_exact_process(telnet, "/var/tmp/atuamax_dnsmasq")
        for name, file in files.items():
            send_file(telnet, access.local_ip, IP, "atuamax-dns-" + name,
                      f"{BASE}/{name}", file.read_bytes())
            print("Instalado:", name, flush=True)
        send_file(telnet, access.local_ip, IP, "atuamax-dns-token",
                  f"{BASE}/token", (token + "\n").encode("ascii"))
        telnet.run(f"chmod 700 {BASE}/dnsweb {BASE}/dnsmasq")
        telnet.run(f"chmod 600 {BASE}/token")
        telnet.run("test -e /var/tmp/atuamax_hosts || echo -n > /var/tmp/atuamax_hosts")
        telnet.run("test -e /var/tmp/atuamax_dns.log || echo -n > /var/tmp/atuamax_dns.log")
        command = (f"{BASE}/dnsmasq --conf-file=/dev/null --port=5353 "
                   f"--listen-address={IP} --bind-interfaces --no-resolv "
                   f"--server={IP}#53 --no-hosts --addn-hosts=/var/tmp/atuamax_hosts "
                   "--pid-file=/var/tmp/atuamax_dns.pid "
                   "--log-facility=/var/tmp/atuamax_dns.log --log-queries "
                   "--user=root --group=root")
        telnet.run(command)
        telnet.run(f"{BASE}/dnsweb")
        time.sleep(2)
    response = requests.get(f"http://{IP}:8088/api/status",
                            headers={"X-DNS-Key": token}, timeout=8)
    response.raise_for_status()
    if not response.json().get("running"):
        raise RuntimeError("Painel iniciou, mas o resolvedor DNS não iniciou")
    print(f"Painel: http://{IP}:8088/")
    print(f"Chave do painel neste PC: {TOKEN_FILE}")
    print("Importe um arquivo .txt/.hosts e aplique antes de ativar o teste de 5 minutos.")


if __name__ == "__main__":
    main()
