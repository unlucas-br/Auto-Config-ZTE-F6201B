# Referências de firmware sem distribuição de imagens

Os perfis N6 e N7 foram preparados a partir de leituras locais dos bancos `mtd7` e `mtd8` de ONTs ZXHN F6201B UNI usadas nos testes. Os dumps e os backups completos permanecem fora deste repositório. O projeto publica apenas metadados necessários para reconhecer o layout e conferir o equipamento conectado.

| Versão | Região analisada | Tamanho | SHA-256 da imagem base |
| --- | --- | ---: | --- |
| N6 | `mtd7`/`mtd8`, a partir do offset `131072` | 26.738.688 bytes | `4dfa5a48783f28c4a122aea97e490e9670b1f50590062bd014d00d29229476ad` |
| N7 | `mtd7`, a partir do offset `0` | 27.131.904 bytes | `94d75b8039a416b3861ec5d5d332076d32026c5c74f8f98a05396b3304cdd0fd` |
| N7 | `mtd8`, a partir do offset `0` | 27.131.904 bytes | `f11c698b78fb10951509b0b145b90819b8ea03f4648cbdaf660f5929f29c0782` |

No N6, os dois bancos analisados tinham o mesmo SHA-256. No N7, os bancos tinham hashes distintos. Os valores também constam dos perfis das marcas para validação durante o uso.

O utilitário lê `/proc/cmdline` para identificar o banco ativo, compara a região encontrada na própria ONT com o hash esperado e verifica o layout JFFS2 antes de preparar qualquer gravação. O nome da versão sozinho não autoriza uma alteração.

As imagens do fabricante não são fornecidas, nem fazem parte dos pacotes Windows. Para reparar ou atualizar uma ONT, use os meios e arquivos autorizados para o equipamento.
