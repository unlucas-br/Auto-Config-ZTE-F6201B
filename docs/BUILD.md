# Executar e gerar as builds Windows

## Código-fonte

Requer Windows, Python 3.12 e acesso Ethernet a uma F6201B compatível. Dentro da pasta da marca:

```powershell
python -m pip install -r requirements.txt
python "Personalizador F6201B.pyw"
```

O programa cria `backups/` ao lado dos arquivos de execução. Essa pasta não deve ser versionada nem compartilhada.

## Build

Na raiz do repositório:

```powershell
python -m pip install 'pyinstaller>=6,<7'
.\build.ps1 -Marca Atuamax
.\build.ps1 -Marca Netflex
```

O script gera a pasta `dist/` da marca e atualiza o ZIP Windows correspondente. Extraia o ZIP inteiro para uso; a build precisa de `resources/`, `resources_n7/`, `stock_n6/`, `stock_n7/` e dos perfis JSON ao lado do EXE.

As dependências de execução estão em `requirements.txt` de cada marca. A build publicada foi produzida no Windows 64 bits com Python 3.12 e PyInstaller 6.

## Conferência dos recursos

`theme.load_profile()` verifica o SHA-256 dos arquivos de `resources/` e `resources_n7/` antes de preparar uma gravação. Se um CSS, logo ou script for alterado diretamente, o perfil precisa ser atualizado de forma consciente e o tema revalidado antes de gerar outra build. Um simples ZIP com arquivos editados não passa automaticamente pelas validações.

Para conferir os perfis, o empacotamento e as imagens sem conectar uma ONT:

```powershell
python tests/verify_release.py
```
