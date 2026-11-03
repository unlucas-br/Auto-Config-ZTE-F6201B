# Desenvolvimento e validação até a versão atual

## 1. Estudo da ONT e do backup

- O objetivo inicial era personalizar a página de login e os menus da F6201B, com logo e cores da marca.
- A página web aceitava a alteração visual, mas um reset físico removia os arquivos aplicados somente ao sistema em execução.
- O pacote de firmware montado para upload web foi recusado na verificação de integridade. A partir disso, a análise passou a usar leituras dos bancos internos da própria ONT.
- Com acesso administrativo à interface web, o fluxo de fábrica autenticado forneceu credenciais Telnet temporárias. O programa implementa esse fluxo, inclusive o desafio `re_rand`, e não grava essas credenciais no projeto.

## 2. Mapeamento de firmware e bancos

- Foram lidas as regiões `mtd7` e `mtd8` de ONTs com firmware `V9.3.10P7N6` e `V9.3.10P7N7`.
- Os arquivos web foram localizados no sistema de arquivos JFFS2. A análise identificou os inodes, as versões dos nós, os tamanhos de página e os blocos reservados para sobreposição.
- O banco ativo passou a ser determinado pelo marcador de U-Boot em `/proc/cmdline`, com checagem cruzada da região indicada.
- O perfil de cada versão registra hashes da imagem base, tamanhos, offsets, metadados dos arquivos e hashes dos recursos. A proveniência das leituras e os recortes estão documentados em [FIRMWARE.md](FIRMWARE.md); os dumps permanecem locais.

## 3. Personalização persistente

1. Identificar versão, banco ativo e banco inativo.
2. Salvar a imagem do banco inativo e os blocos examinados em `backups/`.
3. Comparar os hashes e conferir o bloco de destino. Se houver camada de tema anterior validada, avançar até o próximo bloco vazio.
4. Montar nós JFFS2 novos para os arquivos de login, logo, CSS e o script de clientes Wi-Fi. Recalcular CRC, tamanhos e versões dos inodes.
5. Transferir o payload para a RAM da ONT e comparar os bytes recebidos.
6. Gravar somente o bloco validado do banco inativo, reler e comparar byte a byte.
7. Trocar o banco de boot, reiniciar e conferir os recursos servidos pela página.
8. Repetir o processo no segundo banco.

Esse processo foi usado para manter o visual após reinício e reset físico. A opção **Restaurar interface ZTE** aplica os arquivos visuais originais nos dois bancos e não apaga as configurações da ONT.

## 4. Marcas e recursos

As versões Atuamax e Netflex usam o mesmo mecanismo de validação e gravação. Cada pasta tem seu próprio `brand.json`, logo, CSS, perfis de hash, recursos N6/N7 e pacote Windows. Os nomes e funções dos menus originais foram preservados.

Foi adicionada uma opção para nomear as redes principais de 2,4 e 5 GHz como `Marca_XXXX`, com os quatro últimos caracteres do MAC. Ela é separada da gravação visual, salva a configuração anterior e não altera as senhas Wi-Fi. A persistência desse nome após reset em uma ONT nova ainda requer validação específica.

O firmware já apresentava RSSI em **Rede local > Status**. O script web foi atualizado para consultar os clientes a cada **2 segundos** enquanto a área estiver aberta, indicar o horário da leitura e substituir linhas anteriores em vez de acumulá-las. Em uma validação com cliente conectado, foram observadas seis consultas em 12 segundos e uma única linha atualizada para o cliente. Após a gravação final Netflex, o navegador confirmou seis consultas em 12 segundos; naquele momento, o cliente Wi-Fi estava desconectado.

## 5. Validações da versão publicada

- Sintaxe dos scripts web N6/N7 conferida.
- Montagem e restauração offline das sete camadas de arquivo testadas para ambas as marcas e versões.
- Compatibilidade de restauração com temas antigos de seis arquivos verificada.
- Builds Windows geradas para ambas as marcas; os pacotes estão nas pastas respectivas.
- Netflex N6 gravada e conferida nos dois bancos em uma ONT de teste. Atuamax N6 e N7 foram validadas em etapas anteriores de personalização; a mudança final de intervalo para 2 segundos também foi conferida em navegador antes da publicação.

Os logs e backups de campo são locais. Eles não entram no Git porque podem conter MACs, configurações e outros dados de cada ONT.

## Referências consultadas durante a investigação

- [zte-config-utility](https://github.com/mkst/zte-config-utility): estudo dos backups `config.bin` e da estrutura de configuração ZTE.
- [zteconfigdl](https://github.com/xCuri0/zteconfigdl): comparação dos caminhos de obtenção de configuração.
- [Ratr](https://github.com/Jakiboy/Ratr): referência de interface gráfica para análise de configurações.

Esses projetos não são incorporados às pastas Atuamax e Netflex. O fluxo final publicado aqui usa os arquivos e perfis validados da F6201B.
