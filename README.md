# MangaDex_Downloader_CJrTools

> **Downloader Desktop (GUI & CLI) de alta performance para MangaDex, MangaLivre e fontes web com Design System Dark Minimalista, Fila de Tarefas, Estimativa de Tempo/Tamanho e Empacotamento CBZ.**

---

## 📸 Identidade Visual & Design System

Desenvolvido segundo especificações técnicas de design industrial minimalista:
- **Tema:** Dark Flat Geométrico (`#2E2D2D` background, `#FFAC2B` accent dourado, `#363535` surface).
- **Ícones:** Vetoriais de alta fidelidade baseados em *Phosphor Icons*.
- **Controle Total:** Fila com pausa, retomada automática (Smart Resume), cancelamento individual e métricas em tempo real (velocidade em MB/s e estimativa de tempo de conclusão).

---

## 🚀 Principais Recursos

- **Suporte Multi-Provedor:**
  - **MangaDex (API v5):** Suporte nativo completo com seleção de idioma, deduplicação de versões e modo DataSaver.
  - **MangaLivre:** Extração direta de capítulos e páginas com contorno de bloqueios de leitura.
  - **Madara CMS (WordPress):** Suporte a centenas de scans baseadas no motor WordPress Madara / WP-Manga.
  - **Extrator Universal Heurístico:** Fallback automático para páginas de mangá via sniffer de rede integrado.
- **Gerenciador de Fila de Tarefas:**
  - Estimativa antecipada de tamanho total (MB/GB) e tempo estimado para download.
  - Execução sequencial com controle de threads paralelas por capítulo (padrão: 4 workers).
  - Pausar, Retomar e Cancelar tarefas ativas sem perder progresso.
  - Importação de links em lote via arquivos de texto (`.txt`).
- **Modos Flexíveis de Seleção de Capítulos:**
  - **Todos:** Baixa a obra completa do início ao fim.
  - **Único:** Baixa apenas um capítulo específico (ex: `12` ou `45.5`).
  - **Intervalo:** Baixa do capítulo X ao Y (ex: `1-20` ou `50~100`).
  - **Blocos (Chunk):** Baixa em lotes (ex: primeiros `10`).
  - **Mais Recente:** Baixa apenas o último capítulo lançado.
  - **Personalizado:** Expressões flexíveis combinadas (ex: `1, 3, 5-10, oneshot`).
- **Empacotamento Automático:**
  - Agrupamento de páginas nomeadas ordenadamente (`001.jpg`, `002.jpg`...).
  - Compactação direta no formato padrão para leitores de quadrinhos digitais (`.cbz`).
  - Limpeza automática de arquivos residuais e pastas temporárias após o empacotamento.
- **Interfaces Duplas:**
  - **Interface Gráfica Completa (GUI):** `mangadex_gui.py` via PyQt5.
  - **Linha de Comando (CLI):** `mangadex-dl.py` via argparse para automações, servidores ou uso no terminal.

---

## 🛡️ Segurança e Hardening de Código

O projeto passou por uma rigorosa auditoria de segurança de software defensivo:
- **Proteção contra Path Traversal:** Implementação de `safe_path_join` com canonicalização canônica estrita (`os.path.realpath` / `os.path.commonpath`), impedindo qualquer escape de diretório de destino.
- **Sanitização Robusta de Nomes:** A função `clean_filename` neutraliza caracteres inválidos no Windows/Linux, remove caracteres de controle ASCII (`\x00` a `\x1f`), trata nomes reservados do Windows (`CON`, `PRN`, `AUX`, `NUL`, etc.) e limita comprimento para evitar estouro de `MAX_PATH`.
- **Validação de Protocolos de Rede:** Rejeição explícita de esquemas de arquivo local (`file://`), permitindo estritamente conexões remotas via `http://` e `https://`.
- **Navegador Seguro:** Isolamento do contexto web sem flags perigosas que desativem a Same-Origin Policy (SOP).
- **Persistência Atômica:** Salvamento de estado da fila via arquivos temporários e substituição atômica (`os.replace`), prevenindo corrupção de dados por interrupções abruptas.
- **Privilégio Mínimo:** O software é projetado para rodar em espaço de usuário comum, sem exigir direitos de Administrador ou `root`.

---

## 📦 Estrutura do Projeto

```text
mangadex-dl/
├── assets/
│   ├── icons/            # Ícones vetoriais Phosphor Icons (regular e fill)
│   ├── logo.png          # Logomarca oficial CJR DOOM
│   └── logo.jpg          # Logomarca em alta resolução
├── tests/
│   ├── test_design_system.py    # Validação da identidade visual e tokens
│   └── test_security_and_core.py # Validação de segurança, path traversal e core
├── .github/
│   ├── workflows/ci.yml         # Pipeline automatizado de CI (testes, lint e SAST)
│   └── dependabot.yml           # Atualizações semanais automatizadas de dependências
├── about_dialog.py       # Diálogo "Sobre" oficial do software
├── icons.py              # Provedor dinâmico e vetorial de ícones
├── manga_core.py         # Núcleo de downloads, fila, persistência e segurança
├── mangadex-dl.py        # Ponto de entrada da Interface em Linha de Comando (CLI)
├── mangadex_gui.py       # Ponto de entrada da Interface Gráfica (GUI)
├── mangalivre.py         # Módulo de raspagem e download para mangalivre
├── providers.py          # Provedores de mangá (MangaDex, MangaLivre, Madara, Universal)
├── styles.py             # Design Tokens e folhas de estilo CSS/QSS oficiais
├── MangaDex_Downloader_CJrTools.spec # Especificação PyInstaller para build de executáveis
├── requirements.txt      # Dependências de execução
├── requirements-dev.txt  # Dependências de desenvolvimento e testes
├── pyproject.toml        # Metadados e configurações de linters/scanners
├── .editorconfig         # Padronização de codificação e estilo de arquivos
├── .gitignore            # Exclusão de artefatos de build, dados e temporários
├── SECURITY.md           # Política de reporte de vulnerabilidades
├── CONTRIBUTING.md       # Guia para novos desenvolvedores
└── README.md             # Esta documentação
```

---

## ⚙️ Instalação e Execução

### 1. Pré-requisitos
- Python 3.10 ou superior instalado no sistema.
- Gerenciador de pacotes `pip`.

### 2. Clonando e Configurando o Ambiente

```bash
# Clone o repositório
git clone https://github.com/carlosjrgit/MangaDex_Downloader_CJrTools.git
cd MangaDex_Downloader_CJrTools

# Crie um ambiente virtual (recomendado)
python -m venv .venv

# Ative o ambiente virtual:
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate

# Instale as dependências
pip install --upgrade pip
pip install -r requirements.txt
```

*(Opcional)* Se desejar suporte completo ao extrator universal web:
```bash
pip install playwright
playwright install chromium
```

---

## 🖥️ Como Usar

### Interface Gráfica (GUI)
Para iniciar a aplicação desktop:
```bash
python mangadex_gui.py
```

1. Cole uma ou mais URLs de obras no campo de texto ou importe uma lista via botão **Arquivo .txt**.
2. Clique em **Adicionar à Fila**.
3. Selecione o modo de capítulos desejado (Todos, Intervalo, etc.).
4. Clique em **Iniciar Downloads**. O progresso, estimativas e métricas ao vivo serão atualizados na interface.

### Linha de Comando (CLI)
Exemplos práticos de uso no terminal:

```bash
# Baixar obra completa do MangaDex
python mangadex-dl.py https://mangadex.org/title/a1c7c817-4e59-43b7-9365-09675a149a6f

# Baixar apenas os capítulos de 1 a 10
python mangadex-dl.py https://mangadex.org/title/a1c7c817-4e59-43b7-9365-09675a149a6f --range 1-10

# Baixar lista de URLs a partir de um arquivo .txt com 8 threads simultâneas
python mangadex-dl.py -f mangas.txt -j 8

# Baixar apenas o capítulo mais recente do MangaLivre
python mangadex-dl.py https://mangalivre.blog/manga/eleceed/ --latest

# Retomar fila de downloads pendentes anterior
python mangadex-dl.py --resume
```

---

## 🧪 Testes Automatizados

O projeto possui suítes abrangentes de testes unitários para o Design System, tokens, persistência, estimativas, sanitização de caminhos e validação de segurança:

```bash
python -m unittest discover tests -v
```

---

## 🏗️ Gerando o Executável (.exe)

Para gerar uma versão executável standalone para Windows utilizando o PyInstaller:

```bash
# Instale as dependências de build
pip install pyinstaller

# Execute a compilação a partir do arquivo spec oficial
pyinstaller "MangaDex_Downloader_CJrTools.spec"
```
O executável gerado estará localizado na pasta `dist/`.

---

## 📄 Licença

Consulte a documentação e histórico do projeto para detalhes sobre termos de uso e redistribuição. O núcleo original do downloader baseia-se em código distribuído sob a licença **GNU General Public License v3.0 (GPLv3)**.
