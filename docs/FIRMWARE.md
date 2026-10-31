# Imagens de firmware de referência

## Origem

Os arquivos foram obtidos por **leitura** dos bancos `mtd7` e `mtd8` de ONTs ZXHN F6201B UNI às quais havia acesso administrativo e Telnet temporário. O acesso Telnet foi gerado pelo fluxo de modo de fábrica autenticado com as credenciais web informadas durante os testes. As leituras foram feitas antes de preparar cada gravação, com backup e conferência de hash.

As imagens deste diretório são somente a região da **imagem base do banco**. Blocos de personalização, configuração operacional, backups completos e dados de uma ONT específica ficaram fora do repositório.

| Versão | Arquivo | Recorte da partição | Tamanho | SHA-256 |
| --- | --- | --- | ---: | --- |
| N6 | [`bank_image.bin`](../firmware/V9.3.10P7N6/bank_image.bin) | `mtd7`, offset `131072` | 26.738.688 bytes | `4dfa5a48783f28c4a122aea97e490e9670b1f50590062bd014d00d29229476ad` |
| N7 | [`mtd7_bank_image.bin`](../firmware/V9.3.10P7N7/mtd7_bank_image.bin) | `mtd7`, offset `0` | 27.131.904 bytes | `94d75b8039a416b3861ec5d5d332076d32026c5c74f8f98a05396b3304cdd0fd` |
| N7 | [`mtd8_bank_image.bin`](../firmware/V9.3.10P7N7/mtd8_bank_image.bin) | `mtd8`, offset `0` | 27.131.904 bytes | `f11c698b78fb10951509b0b145b90819b8ea03f4648cbdaf660f5929f29c0782` |

No N6, as imagens base lidas de `mtd7` e `mtd8` tinham o mesmo SHA-256. No N7, os bancos tinham hashes distintos e ambos constam aqui. Os hashes também estão em [`SHA256SUMS.txt`](../firmware/SHA256SUMS.txt) e nos perfis das duas marcas.

## Como conferir

No PowerShell:

```powershell
Get-FileHash .\firmware\V9.3.10P7N6\bank_image.bin -Algorithm SHA256
Get-FileHash .\firmware\V9.3.10P7N7\mtd7_bank_image.bin -Algorithm SHA256
Get-FileHash .\firmware\V9.3.10P7N7\mtd8_bank_image.bin -Algorithm SHA256
```

O utilitário lê `/proc/cmdline` para identificar o banco ativo, compara a região de firmware com o hash esperado, verifica o layout JFFS2 e só então considera um bloco vazio no banco inativo. Em N6, uma variante com cabeçalho de firmware é reconhecida mediante validação do conteúdo e CRC. O nome da versão sozinho não autoriza a gravação.

**Estes `.bin` não são arquivos de atualização da interface web.** Não os envie pela página de upgrade e não grave uma imagem de referência inteira em uma ONT. Eles também não substituem um backup próprio da ONT.

## Limites de publicação

Os arquivos vêm de firmware ZTE. Esta documentação descreve sua proveniência técnica e os hashes; não declara titularidade nem licença sobre o firmware do fabricante. Antes de tornar o repositório público, confira os direitos de redistribuição aplicáveis.
