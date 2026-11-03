# Proteção DNS Atuamax — teste local

Painel de bloqueio DNS executado **na F6201B**, em `http://192.168.1.1:8088/`. Esta etapa foi validada na V9.3.10P7N6, com a ONT **sem Internet**. O serviço usa a partição `/Plugin` (mtd10) para os executáveis e o painel, `/Pluginlog` (mtd11) para a lista salva, e RAM (`/var/tmp`) para o arquivo de bloqueio e os logs. Não altera o `dnsmasq` gerenciado pela ZTE.

## Instalar e testar

1. Conecte uma única F6201B à Ethernet do PC e confirme o endereço `192.168.1.1`.
2. Na pasta `Atuamax`, instale as dependências de `requirements.txt`.
3. Execute `python experimental_dns/instalar_teste.py` e informe a conta web administrativa **atual** do equipamento. A ferramenta gera o acesso Telnet temporário e inicia os dois serviços de teste.
4. Abra `http://192.168.1.1:8088/`. Na primeira ação, informe a chave gerada em `experimental_dns/.local-admin-token` no **PC**. Esse arquivo é individual e está excluído do Git.
5. Use **Importar arquivo** para selecionar uma lista `.txt` ou `.hosts` no PC. Clique em **Aplicar listas na ONT** e então, se desejar, **Ativar por 5 min**.
6. **Desativar** remove o redirecionamento imediatamente; **Limpar teste** remove também as listas. O redirecionamento expira sozinho em cinco minutos.

O botão de ativação afeta somente consultas DNS **deste PC para `192.168.1.1:53`**. Outros clientes da rede continuam no serviço original. Como a ONT usada no teste não tem Internet, domínios permitidos podem não obter resposta. Navegadores com DNS seguro próprio podem ignorar o DNS da ONT.

## Importação de listas

Nenhuma lista acompanha a configuração inicial. Os formatos aceitos são nomes de domínio, linhas `0.0.0.0 dominio`, `127.0.0.1 dominio`, `:: dominio` e regras simples `||dominio^`. Endereços IP isolados são ignorados. A lista de teste `Malicious.txt` do projeto `zangadoprojets/pi-hole-blocklist` foi usada apenas para validação; **não está incluída nem é ativada automaticamente**. No teste, 168.745 domínios válidos foram aplicados e depois removidos.

Uma URL como `https://www.youtube.com/` é um **site**, não um arquivo de lista. O painel coloca esse endereço no campo **Bloquear domínio**. Para importar uma lista por URL, a fonte deve servir texto em formato de lista e o navegador ou a ONT precisa conseguir baixá-la. Sem acesso externo na ONT, baixe o `.txt` no PC por outro meio e use **Importar arquivo**.

O limite de um arquivo é 8 MiB; a combinação final pode conter até 200 mil domínios e 12 MiB em RAM. Permissões removem domínios da combinação antes da aplicação. O bloqueio por `hosts` é exato para o nome listado; subdomínios adicionais precisam constar na lista.

## Estado experimental

O painel e o resolvedor são iniciados pelo instalador. Depois de reiniciar ou resetar a ONT, execute o instalador novamente e clique em **Aplicar listas na ONT** para reconstruir o arquivo em RAM. O teste não instala um serviço permanente no boot nem modifica os bancos de firmware. A lista salva fica em `/Pluginlog/atuamax-dns/state.json` até **Limpar teste**; o contador e o arquivo efetivo ficam em RAM.

## Código e compilação

`server.c` implementa o painel e a API local; `index.html` implementa a interface e o parser de listas. `dnsmasq-arm-softfloat` foi compilado a partir do [dnsmasq 2.91 oficial](https://thekelleys.org.uk/dnsmasq/doc.html) com Zig 0.13.0 para ARM EABI soft-float. O tarball completo do código correspondente está em `upstream/dnsmasq-2.91.tar.gz`, incluindo sua licença. `dnsweb-arm` foi compilado de `server.c` com o mesmo alvo. Para reconstruir ambos:

```powershell
python compilar.py C:/caminho/zig.exe
```

Os arquivos temporários de compilação ficam em `objetos_build/`. A compilação, o bloqueio por arquivo, o redirecionamento por cinco minutos e sua remoção foram testados na ONT N6. A versão N7 e a persistência de boot ainda não foram validadas para este módulo.
