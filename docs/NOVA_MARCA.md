# Adicionar outra marca

1. Copie uma pasta de marca existente para uma pasta nova na raiz, por exemplo `MinhaMarca/`. Preserve os arquivos `stock_n6/` e `stock_n7/`.
2. Ajuste `brand.json`: nome, prefixo do Wi-Fi, cores, saudação e nome do arquivo PNG.
3. Edite o PNG e os arquivos de `resources/` e `resources_n7/` que compõem o visual. Os nomes e as funções do firmware original devem continuar operando.
4. Atualize os hashes de recursos em `profile.json` e `profile_n7.json`, confira o tamanho do payload JFFS2 e valide os dois perfis em uma imagem offline antes de usar uma ONT.
5. Gere a build da nova pasta com os mesmos parâmetros de `build.ps1`, ajustando o nome do EXE e do ZIP.
6. Teste em uma ONT compatível: identificação, backup, gravação e leitura após cada banco, login, menus, RSSI e reset físico.

Cada marca fica autocontida. Os dumps de referência e os backups criados durante testes e produção permanecem locais, fora do repositório.
