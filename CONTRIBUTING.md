# Guia de Contribuição — MangaHubRip_CJrTools

Agradecemos o seu interesse em contribuir para o **MangaHubRip_CJrTools**!
Este documento detalha o fluxo de desenvolvimento local, padrões de qualidade e diretrizes de segurança.

---

## 1. Requisitos de Ambiente

- **Python:** 3.10 ou superior (testado até Python 3.14)
- **Gerenciador de Pacotes:** `pip`
- **Git** instalado localmente

---

## 2. Configuração do Ambiente Local

Recomendamos utilizar um ambiente virtual isolado (`venv`):

```bash
# 1. Clonar o repositório
git clone https://github.com/carlosjrgit/MangaDex_Downloader_CJrTools.git
cd MangaDex_Downloader_CJrTools

# 2. Criar o ambiente virtual
python -m venv .venv

# 3. Ativar o ambiente virtual
# No Windows (PowerShell):
.venv\Scripts\Activate.ps1
# No Linux/macOS:
source .venv/bin/activate

# 4. Instalar as dependências de desenvolvimento
pip install --upgrade pip
pip install -r requirements-dev.txt
```

---

## 3. Executando o Projeto

### Interface Gráfica (GUI)
```bash
python mangadex_gui.py
```

### Linha de Comando (CLI)
```bash
python mangadex-dl.py --help
```

---

## 4. Testes Automatizados

Antes de submeter qualquer alteração ou Pull Request, garanta que todos os testes automatizados passem:

```bash
python -m unittest discover tests -v
```

Ao adicionar novas funcionalidades ou corrigir problemas de segurança, **crie testes de regressão** correspondentes no diretório `tests/`.

---

## 5. Qualidade e Segurança de Código

Execute as ferramentas de verificação estática antes de submeter alterações:

```bash
# Lint e formatação (Ruff)
ruff check .

# Análise Estática de Segurança (Bandit)
bandit -r . -c pyproject.toml
```

---

## 6. Diretrizes de Segurança para Colaboradores

- **NUNCA comite credenciais, segredos, arquivos de sessão ou dados pessoais.**
- Respeite o `.gitignore` e não force o envio de arquivos de download, executáveis binários compilados (`dist/`) ou caches.
- Qualquer entrada de rede ou filename deve passar pela sanitização via `safe_path_join` e `clean_filename` de `manga_core.py`.
- Mantenha o princípio do menor privilégio e não adicione elevação de permissão.
