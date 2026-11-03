# Auto Config ZTE F6201B

<div align="center">

**Personalização da interface da ZXHN F6201B UNI para múltiplas marcas**  
Projeto de Lucas Ferraz

</div>

<p align="center">
  <img alt="Python 3.12" src="https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white">
  <img alt="Windows" src="https://img.shields.io/badge/Windows-10%2F11-0078D4?style=for-the-badge&logo=windows&logoColor=white">
  <img alt="F6201B N6 e N7" src="https://img.shields.io/badge/F6201B-N6%20%7C%20N7-ef6b1b?style=for-the-badge">
</p>

<p align="center">
  <a href="#sobre">Sobre</a> |
  <a href="#recursos">Recursos</a> |
  <a href="#instalacao">Instalação</a> |
  <a href="#uso">Uso</a> |
  <a href="#estrutura">Estrutura</a> |
  <a href="#firmware">Firmware</a> |
  <a href="#english">English</a>
</p>

---

<a id="sobre"></a>

## Sobre

Este projeto personaliza a página de login e os menus da **ZTE ZXHN F6201B UNI** sem trocar as funções da interface. Há duas versões prontas: **Atuamax**, com visual laranja, e **Netflex**, com visual azul e laranja. Cada empresa fica em sua própria pasta para facilitar a inclusão de novas marcas.

O programa identifica o equipamento, o firmware e o banco de boot ativo, cria backups, grava a personalização no banco inativo, confere a leitura após a gravação e repete o processo no outro banco. O visual foi testado após reinício e reset físico. A ferramenta recusa layouts e imagens fora dos perfis validados.

Autor: **Lucas Ferraz**  
Linguagem: **Python**  
Plataforma das builds: **Windows 64 bits**

---

<a id="recursos"></a>

## Recursos

- Detecção automática da ONT conectada por Ethernet.
- Perfis para firmware `V9.3.10P7N6` e `V9.3.10P7N7`.
- Logo, saudação, cores, cabeçalho e menus personalizados por marca.
- Indicador de RSSI dos clientes Wi-Fi em **Rede local > Status**, atualizado a cada **2 segundos**.
- Nome opcional das redes 2,4 e 5 GHz no formato `Marca_XXXX`, usando os quatro últimos caracteres do MAC da ONT. As senhas Wi-Fi não são alteradas.
- Backup e conferência byte a byte dos blocos gravados.
- Personalização dos dois bancos para preservar o visual após reset físico.
- Botão para restaurar apenas a interface original da ZTE.
- Módulo experimental de proteção DNS da Atuamax, instalado separadamente na ONT, com importação de listas locais e teste de bloqueio por cinco minutos em um PC.

RSSI é intensidade de sinal em dBm; não representa distância em metros.

---

<a id="instalacao"></a>

## Instalação

Escolha a marca e extraia o pacote Windows **inteiro**. O executável usa arquivos de apoio que ficam ao lado dele.

| Marca | Pacote | Código e recursos |
| --- | --- | --- |
| Atuamax | [Atuamax_Windows_x64.zip](Atuamax/Atuamax_Windows_x64.zip) | [Atuamax/](Atuamax/) |
| Netflex | [Netflex_Windows_x64.zip](Netflex/Netflex_Windows_x64.zip) | [Netflex/](Netflex/) |

Para executar o código-fonte, use Python 3.12 no Windows:

```powershell
cd Atuamax # ou Netflex
python -m pip install -r requirements.txt
python "Personalizador F6201B.pyw"
```

Para gerar uma nova build, consulte [BUILD.md](docs/BUILD.md).

O [módulo experimental de proteção DNS](Atuamax/experimental_dns/README.md) fica na pasta Atuamax e usa um instalador Python próprio. Ele não faz parte do ZIP do personalizador nem é instalado automaticamente ao personalizar a interface.

---

<a id="uso"></a>

## Uso

1. Conecte **uma** F6201B por vez à Ethernet do PC e aguarde a rede estabilizar.
2. Abra o personalizador da marca e clique em **Detectar**.
3. Informe as credenciais **atuais da interface web com permissão administrativa**. O formulário pode mostrar valores iniciais, mas eles precisam corresponder ao equipamento conectado.
4. Revise a saudação, o PNG e a opção de nomear redes Wi-Fi.
5. Clique em **Personalizar ONT**. Mantenha a energia e a Ethernet conectadas durante os dois ciclos de backup, gravação e reinício.
6. Após a conclusão, confira o login, os menus e **Rede local > Status**. Use **Verificar reset físico** se fizer esse teste.

**Restaurar interface ZTE** reverte os arquivos visuais dos dois bancos. Essa operação não equivale a restaurar as configurações de fábrica. O reset físico, por sua vez, apaga as configurações operacionais da ONT.

Os backups de cada execução ficam na pasta `backups/` ao lado do programa e **não são publicados neste repositório**, pois podem conter dados do equipamento.

---

<a id="estrutura"></a>

## Estrutura

```text
.
├── Atuamax/                # fonte, temas N6/N7 e pacote Windows da Atuamax
│   └── experimental_dns/    # painel DNS experimental, binários ARM e código-fonte
├── Netflex/                # fonte, temas N6/N7 e pacote Windows da Netflex
├── docs/                   # obtenção, processo e build
└── README.md
```

As pastas das marcas são independentes. Para criar outra, copie uma delas, ajuste `brand.json`, PNG, CSS e textos, e gere novos perfis de hash para os recursos modificados. [Como criar outra marca](docs/NOVA_MARCA.md).

---

<a id="firmware"></a>

## Firmware

Os dumps de firmware usados na análise **não são distribuídos** neste repositório. [FIRMWARE.md](docs/FIRMWARE.md) registra apenas a proveniência, o layout e os hashes necessários à validação; [PROCESSO.md](docs/PROCESSO.md) descreve a sequência de desenvolvimento.

As builds só gravam quando o modelo, a versão, a imagem base, o banco ativo e o espaço de destino passam pelas validações. Um firmware com o mesmo nome de versão, mas conteúdo diferente, pode ser recusado.

---

<a id="english"></a>

## English

This repository contains Windows GUI customizers for the ZTE ZXHN F6201B UNI, with separate Atuamax and Netflex themes. It supports the validated N6 and N7 firmware layouts, backs up and checks both boot banks, and adds a 2-second Wi-Fi client RSSI refresh. Manufacturer firmware dumps, device backups and credentials are not included.

See the Portuguese sections above for installation, supported versions, usage and technical documentation.
