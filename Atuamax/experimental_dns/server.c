/* Small local HTTP API for the experimental F6201B DNS panel.
 * The browser imports lists; this process validates and installs only the
 * merged hosts file. It never changes the ZTE DNS process or its arguments.
 */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define BASE "/Plugin/atuamax-dns"
#define RAM_HOSTS "/var/tmp/atuamax_hosts"
#define STATE_FILE "/Pluginlog/atuamax-dns/state.json"
#define MAX_BODY (12 * 1024 * 1024)
#define MAX_SOURCE (8 * 1024 * 1024)
#define MAX_HEADERS 16384

static char token[128];
static unsigned current_domains;
static char active_ip[INET_ADDRSTRLEN];
static time_t active_until;
static int listener_fd = -1;
static pid_t timer_pid;

static int iptables_rule(const char *action, const char *ip, const char *protocol) {
  pid_t child = fork();
  if (child == 0) {
    int nullfd = open("/dev/null", O_WRONLY);
    if (nullfd >= 0) { dup2(nullfd, 1); dup2(nullfd, 2); }
    if (!strcmp(action, "-I"))
      execl("/bin/iptables", "iptables", "-t", "nat", "-I", "PREROUTING", "1",
            "-s", ip, "-d", "192.168.1.1", "-p", protocol, "--dport", "53",
            "-j", "REDIRECT", "--to-ports", "5353", (char *)NULL);
    else
      execl("/bin/iptables", "iptables", "-t", "nat", "-D", "PREROUTING",
            "-s", ip, "-d", "192.168.1.1", "-p", protocol, "--dport", "53",
            "-j", "REDIRECT", "--to-ports", "5353", (char *)NULL);
    _exit(127);
  }
  int result = -1;
  if (child < 0 || waitpid(child, &result, 0) < 0) return -1;
  return WIFEXITED(result) ? WEXITSTATUS(result) : -1;
}

static void disable_redirect(void) {
  if (!active_ip[0]) return;
  if (timer_pid > 1) {
    kill(timer_pid, SIGTERM);
    waitpid(timer_pid, NULL, 0);
    timer_pid = 0;
  }
  iptables_rule("-D", active_ip, "udp");
  iptables_rule("-D", active_ip, "tcp");
  active_ip[0] = 0;
  active_until = 0;
}

static int send_all(int fd, const void *data, size_t size) {
  const char *p = data;
  while (size) {
    ssize_t n = send(fd, p, size, 0);
    if (n <= 0) return -1;
    p += n; size -= (size_t)n;
  }
  return 0;
}

static void reply(int fd, int status, const char *type, const void *data, size_t size) {
  char head[320];
  const char *label = status == 200 ? "OK" : status == 400 ? "Bad Request" :
                      status == 401 ? "Unauthorized" : status == 404 ? "Not Found" :
                      status == 413 ? "Payload Too Large" : "Internal Server Error";
  int n = snprintf(head, sizeof(head),
    "HTTP/1.1 %d %s\r\nContent-Type: %s\r\nContent-Length: %zu\r\n"
    "Cache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\n"
    "X-Frame-Options: SAMEORIGIN\r\nConnection: close\r\n\r\n",
    status, label, type, size);
  if (n > 0 && (size_t)n < sizeof(head)) {
    send_all(fd, head, (size_t)n);
    if (size) send_all(fd, data, size);
  }
}

static void error(int fd, int status, const char *message) {
  reply(fd, status, "text/plain; charset=utf-8", message, strlen(message));
}

static char *read_file(const char *path, size_t limit, size_t *size) {
  FILE *fp = fopen(path, "rb");
  if (!fp) return NULL;
  if (fseek(fp, 0, SEEK_END) || (long)(*size = (size_t)ftell(fp)) < 0 || *size > limit || fseek(fp, 0, SEEK_SET)) {
    fclose(fp); return NULL;
  }
  char *data = malloc(*size + 1);
  if (!data) { fclose(fp); return NULL; }
  if (fread(data, 1, *size, fp) != *size) { free(data); fclose(fp); return NULL; }
  fclose(fp); data[*size] = 0; return data;
}

static bool write_atomic(const char *path, const char *data, size_t size) {
  char temp[256];
  if (snprintf(temp, sizeof(temp), "%s.new", path) >= (int)sizeof(temp)) return false;
  int fd = open(temp, O_WRONLY | O_CREAT | O_TRUNC, 0600);
  if (fd < 0) return false;
  size_t pos = 0;
  while (pos < size) {
    ssize_t n = write(fd, data + pos, size - pos);
    if (n <= 0) { close(fd); unlink(temp); return false; }
    pos += (size_t)n;
  }
  bool ok = fsync(fd) == 0 && close(fd) == 0 && rename(temp, path) == 0;
  if (!ok) unlink(temp);
  return ok;
}

static bool domain_valid(const char *s) {
  size_t len = strlen(s), label = 0;
  bool dot = false;
  if (len < 3 || len > 253) return false;
  for (size_t i = 0; i < len; i++) {
    char c = s[i];
    if (c == '.') {
      if (!label || label > 63 || s[i - 1] == '-') return false;
      label = 0; dot = true; continue;
    }
    if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-')) return false;
    if (!label && c == '-') return false;
    label++;
  }
  return dot && label && label <= 63 && s[len - 1] != '-';
}

static bool hosts_valid(char *body, size_t length, unsigned *domains) {
  if (!length || length > MAX_BODY || body[length - 1] != '\n') return false;
  if (memchr(body, 0, length)) return false;
  unsigned lines = 0;
  char *p = body;
  while (*p) {
    char *end = strchr(p, '\n');
    if (!end) return false;
    char *space = strchr(p, ' ');
    if (!space || space > end) return false;
    char prefix[16];
    size_t prefix_len = (size_t)(space - p);
    if (prefix_len >= sizeof(prefix)) return false;
    memcpy(prefix, p, prefix_len); prefix[prefix_len] = 0;
    if (strcmp(prefix, "0.0.0.0") && strcmp(prefix, "::")) return false;
    char saved = *end; *end = 0;
    bool valid = domain_valid(space + 1);
    *end = saved;
    if (!valid || ++lines > 400000) return false;
    p = end + 1;
  }
  *domains = lines / 2;
  return true;
}

static void serve_file(int fd, const char *path, const char *type, size_t max) {
  size_t size = 0;
  char *data = read_file(path, max, &size);
  if (!data) { error(fd, 404, "Arquivo indisponível"); return; }
  reply(fd, 200, type, data, size);
  free(data);
}

static bool authorized(const char *headers) {
  const char *found = strcasestr(headers, "X-DNS-Key:");
  if (!found) return false;
  found += strlen("X-DNS-Key:");
  while (*found == ' ') found++;
  const char *end = strpbrk(found, "\r\n");
  if (!end) end = found + strlen(found);
  return (size_t)(end - found) == strlen(token) &&
         !memcmp(found, token, strlen(token));
}

static unsigned count_log(const char *needle) {
  FILE *fp = fopen("/var/tmp/atuamax_dns.log", "r");
  if (!fp) return 0;
  char line[512]; unsigned count = 0;
  while (fgets(line, sizeof(line), fp)) if (strstr(line, needle)) count++;
  fclose(fp); return count;
}

static void status_json(int fd) {
  int pid = 0;
  FILE *fp = fopen("/var/tmp/atuamax_dns.pid", "r");
  if (fp) { fscanf(fp, "%d", &pid); fclose(fp); }
  bool running = pid > 1 && kill(pid, 0) == 0;
  char body[256];
  bool redirect = active_ip[0] && time(NULL) < active_until;
  int n = snprintf(body, sizeof(body), "{\"running\":%s,\"domains\":%u,\"queries\":%u,\"blocked\":%u,\"redirect\":%s,\"expires_in\":%ld}",
                   running ? "true" : "false", current_domains,
                   count_log("query["), count_log(" is 0.0.0.0"),
                   redirect ? "true" : "false", redirect ? (long)(active_until - time(NULL)) : 0L);
  reply(fd, 200, "application/json; charset=utf-8", body, (size_t)n);
}

static void handle_client(int fd, const struct sockaddr_in *peer) {
  struct timeval timeout = {.tv_sec = 8, .tv_usec = 0};
  setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
  char header[MAX_HEADERS + 1]; size_t used = 0; char *end = NULL;
  while (used < MAX_HEADERS) {
    ssize_t n = recv(fd, header + used, MAX_HEADERS - used, 0);
    if (n <= 0) return;
    used += (size_t)n; header[used] = 0;
    end = strstr(header, "\r\n\r\n");
    if (end) break;
  }
  if (!end) { error(fd, 413, "Cabeçalhos grandes demais"); return; }
  size_t head_size = (size_t)(end + 4 - header);
  *end = 0;
  char method[8], path[96];
  if (sscanf(header, "%7s %95s", method, path) != 2) { error(fd, 400, "Requisição inválida"); return; }
  if (!strcmp(method, "GET") && !strcmp(path, "/")) {
    serve_file(fd, BASE "/index.html", "text/html; charset=utf-8", 100000); return;
  }
  if (!strcmp(method, "GET") && !strcmp(path, "/logo.png")) {
    serve_file(fd, BASE "/logo.png", "image/png", 100000); return;
  }
  if (!authorized(header)) { error(fd, 401, "Chave do painel necessária"); return; }
  if (!strcmp(method, "GET") && !strcmp(path, "/api/status")) { status_json(fd); return; }
  if (!strcmp(method, "GET") && !strcmp(path, "/api/state")) {
    serve_file(fd, STATE_FILE, "application/json; charset=utf-8", MAX_BODY); return;
  }
  if (strcmp(method, "POST")) { error(fd, 404, "Rota desconhecida"); return; }
  if (!strcmp(path, "/api/enable")) {
    if (!current_domains) { error(fd, 400, "Aplique uma lista antes de ativar o teste"); return; }
    if (active_ip[0] && time(NULL) >= active_until) disable_redirect();
    if (active_ip[0] && time(NULL) < active_until) {
      error(fd, 400, "Já existe um teste ativo. Desative-o primeiro."); return;
    }
    char ip[INET_ADDRSTRLEN];
    if (!inet_ntop(AF_INET, &peer->sin_addr, ip, sizeof(ip))) {
      error(fd, 500, "Origem não identificada"); return;
    }
    if (iptables_rule("-I", ip, "udp") || iptables_rule("-I", ip, "tcp")) {
      iptables_rule("-D", ip, "udp");
      iptables_rule("-D", ip, "tcp");
      error(fd, 500, "A ONT recusou a regra NAT"); return;
    }
    strncpy(active_ip, ip, sizeof(active_ip) - 1);
    active_ip[sizeof(active_ip) - 1] = 0;
    active_until = time(NULL) + 300;
    pid_t timer = fork();
    if (timer < 0) { disable_redirect(); error(fd, 500, "Temporizador indisponível"); return; }
    if (timer == 0) {
      close(fd); close(listener_fd);
      sleep(300);
      iptables_rule("-D", ip, "udp");
      iptables_rule("-D", ip, "tcp");
      _exit(0);
    }
    timer_pid = timer;
    reply(fd, 200, "application/json", "{\"active\":true,\"expires_in\":300}", 32);
    return;
  }
  if (!strcmp(path, "/api/disable")) {
    disable_redirect();
    reply(fd, 200, "application/json", "{\"active\":false}", 16);
    return;
  }
  if (!strcmp(path, "/api/clear")) {
    disable_redirect();
    if (!write_atomic(RAM_HOSTS, "", 0)) { error(fd, 500, "Falha ao limpar lista"); return; }
    unlink(STATE_FILE);
    current_domains = 0;
    FILE *fp = fopen("/var/tmp/atuamax_dns.pid", "r");
    int pid = 0;
    if (fp) { fscanf(fp, "%d", &pid); fclose(fp); }
    if (pid > 1) kill(pid, SIGHUP);
    reply(fd, 200, "application/json", "{\"domains\":0}", 13);
    return;
  }
  const char *length_header = strcasestr(header, "Content-Length:");
  if (!length_header || (length_header != header && length_header[-1] != '\n')) {
    error(fd, 400, "Content-Length necessário"); return;
  }
  long length = strtol(length_header + 15, NULL, 10);
  if (length < 1 || length > MAX_BODY) { error(fd, 413, "Conteúdo maior que 12 MiB"); return; }
  char *body = malloc((size_t)length + 1);
  if (!body) { error(fd, 500, "Sem memória"); return; }
  size_t received = used - head_size;
  if (received > (size_t)length) received = (size_t)length;
  memcpy(body, header + head_size, received);
  while (received < (size_t)length) {
    ssize_t n = recv(fd, body + received, (size_t)length - received, 0);
    if (n <= 0) { free(body); error(fd, 400, "Envio incompleto"); return; }
    received += (size_t)n;
  }
  body[length] = 0;
  if (!strcmp(path, "/api/fetch")) {
    if (length > 2048 || memchr(body, 0, (size_t)length) ||
        strncmp(body, "https://", 8) || strpbrk(body, "\r\n\t ")) {
      free(body); error(fd, 400, "Informe uma URL HTTPS de lista"); return;
    }
    const char *download = "/var/tmp/atuamax_dns_download";
    unlink(download);
    pid_t child = fork();
    if (child == 0) {
      int nullfd = open("/dev/null", O_WRONLY);
      if (nullfd >= 0) { dup2(nullfd, 1); dup2(nullfd, 2); }
      execl("/bin/curl", "curl", "--fail", "--location", "--max-time", "30",
            "--max-filesize", "8388608", "--proto", "=https", "--proto-redir",
            "=https", "--output", download, body, (char *)NULL);
      _exit(127);
    }
    int result = -1;
    if (child > 0) waitpid(child, &result, 0);
    size_t source_size = 0;
    char *source = WIFEXITED(result) && WEXITSTATUS(result) == 0 ?
      read_file(download, MAX_SOURCE, &source_size) : NULL;
    unlink(download);
    if (!source || !source_size || source[0] == '<') {
      free(source); free(body);
      error(fd, 500, "A ONT não conseguiu baixar uma lista de texto. Baixe o .txt no PC e use Importar arquivo.");
      return;
    }
    reply(fd, 200, "text/plain; charset=utf-8", source, source_size);
    free(source);
  } else if (!strcmp(path, "/api/hosts")) {
    unsigned domains = 0;
    if (!hosts_valid(body, (size_t)length, &domains)) {
      free(body); error(fd, 400, "Lista de domínios inválida"); return;
    }
    if (!write_atomic(RAM_HOSTS, body, (size_t)length)) {
      free(body); error(fd, 500, "Falha ao salvar lista"); return;
    }
    FILE *fp = fopen("/var/tmp/atuamax_dns.pid", "r");
    int pid = 0;
    if (fp) { fscanf(fp, "%d", &pid); fclose(fp); }
    if (pid > 1) kill(pid, SIGHUP);
    current_domains = domains;
    char response[100];
    int n = snprintf(response, sizeof(response), "{\"domains\":%u}", domains);
    reply(fd, 200, "application/json", response, (size_t)n);
  } else if (!strcmp(path, "/api/state")) {
    if (body[0] != '{' || body[length - 1] != '}') {
      error(fd, 400, "Estado inválido");
    } else if (!write_atomic(STATE_FILE, body, (size_t)length)) {
      error(fd, 500, "Falha ao salvar estado");
    } else {
      reply(fd, 200, "application/json", "{}", 2);
    }
  } else error(fd, 404, "Rota desconhecida");
  free(body);
}

int main(void) {
  mkdir("/Pluginlog/atuamax-dns", 0700);
  FILE *hosts = fopen(RAM_HOSTS, "r");
  if (hosts) {
    char line[512];
    while (fgets(line, sizeof(line), hosts))
      if (!strncmp(line, "0.0.0.0 ", 8)) current_domains++;
    fclose(hosts);
  }
  size_t size = 0;
  char *secret = read_file(BASE "/token", sizeof(token) - 1, &size);
  if (!secret || size < 16 || size > 100) return 2;
  while (size && (secret[size - 1] == '\n' || secret[size - 1] == '\r')) size--;
  memcpy(token, secret, size); token[size] = 0; free(secret);
  int listener = socket(AF_INET, SOCK_STREAM, 0);
  if (listener < 0) return 3;
  int yes = 1;
  setsockopt(listener, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
  struct sockaddr_in addr = {.sin_family = AF_INET, .sin_port = htons(8088)};
  inet_pton(AF_INET, "192.168.1.1", &addr.sin_addr);
  if (bind(listener, (void *)&addr, sizeof(addr)) || listen(listener, 8)) return 4;
  listener_fd = listener;
  pid_t child = fork();
  if (child < 0) return 5;
  if (child > 0) return 0;
  if (setsid() < 0) return 6;
  int nullfd = open("/dev/null", O_RDWR);
  if (nullfd >= 0) {
    dup2(nullfd, 0); dup2(nullfd, 1); dup2(nullfd, 2);
    if (nullfd > 2) close(nullfd);
  }
  FILE *pidfile = fopen("/var/tmp/atuamax_dnsweb.pid", "w");
  if (pidfile) { fprintf(pidfile, "%ld\n", (long)getpid()); fclose(pidfile); }
  signal(SIGPIPE, SIG_IGN);
  for (;;) {
    pid_t reaped;
    while ((reaped = waitpid(-1, NULL, WNOHANG)) > 0)
      if (reaped == timer_pid) timer_pid = 0;
    struct sockaddr_in peer; socklen_t peer_len = sizeof(peer);
    int client = accept(listener, (void *)&peer, &peer_len);
    if (client < 0) { if (errno == EINTR) continue; return 5; }
    handle_client(client, &peer);
    close(client);
  }
}
